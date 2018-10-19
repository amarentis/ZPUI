from time import sleep, strftime, localtime
from textwrap import wrap
from threading import Event

from apps import ZeroApp
from ui import Listbox, PrettyPrinter as Printer, NumpadCharInput, Menu, LoadingIndicator, TextReader, UniversalInput, MessagesMenu, rfa, MenuExitException
from helpers import setup_logger, read_or_create_config, local_path_gen, save_config_method_gen

from client import Client, MatrixRequestError

local_path = local_path_gen(__name__)

logger = setup_logger(__name__, "info")

class MatrixClientApp(ZeroApp):

	menu_name = "Matrix Client"
	default_config = '{"user_id":"", "token":"", "your_other_usernames":[]}'
	config_filename = "config.json"

        client = None

	def on_start(self):
		if not self.client:
			if not self.init_and_login():
				return False
		self.display_rooms()

	def init_and_login(self):
		self.stored_messages = {}
		self.messages_menu = None
		self.active_room = ""
		self.seen_events = []
		self.has_processed_new_events = Event()

		self.config = read_or_create_config(local_path(self.config_filename), self.default_config, self.menu_name+" app")
		self.save_config = save_config_method_gen(self, local_path(self.config_filename))

		return self.login()

	# Login the user
	def login(self):
		# Check whether the user has been logged in before
		logged_in_with_token = False
		if self.config['user_id'] and self.config['token']:
			logger.debug("User has been logged in before")

			with LoadingIndicator(self.i, self.o, message="Logging in ..."):
				try:
					self.client = Client(self.config['user_id'], token=self.config['token'])
				except MatrixRequestError as e:
					logger.exception("Wrong or outdated token/username?")
					logger.error(dir(e))
				else:
					logged_in_with_token = self.client.logged_in

		if not logged_in_with_token:

			# Get the required user data
			username = UniversalInput(self.i, self.o, message="Enter username", name="Matrix app username dialog").activate()
			if not username:
				return False

			# Create a matrix user id from the username, currently only ids on matrix.org are possible
			username = "@{}:matrix.org".format(username)

			password = UniversalInput(self.i, self.o, message="Enter password", name="Matrix app password dialog").activate()
			if not username:
				return False

			# Show a beatiful loading animation while setting everything up
			with LoadingIndicator(self.i, self.o, message="Logging in ...") as l:
				self.client = Client(username, password=password)

				# Store username and token
				if self.client.logged_in:
					self.config['user_id'] = username
					self.config['token'] = self.client.get_token()
					self.save_config()

					logger.info("Succesfully logged in")
				else:
					l.pause()
					Printer("Failed to log in", self.i, self.o)
					l.resume()
					return False

		# Get the users rooms
		self.rooms = self.client.get_rooms()

		# Add a listener for new events to all rooms the user is in
		for room_name in self.rooms:
			self.rooms[room_name].add_listener(self._on_message)
			self.stored_messages[room_name] = {}

			# Used to store data for each event
			self.stored_messages[room_name]["events"] = []

		# Start a new thread for the listeners, waiting for events to happen
		self.client.matrix_client.start_listener_thread()

		return True

	# Displays a list of all rooms the user is in
	def display_rooms(self):
		menu_contents = []
		for r in self.rooms:
			current_room = self.rooms[r]

			# Count the amount of backfilled messages for each room
			self.stored_messages[current_room.room_id]["backfilled"] = 0

			# Get the last 10 messages for each room and update stored_messages
			for e in reversed(current_room.get_events()):
				self._on_message(current_room, e)
				# self.stored_messages[current_room.room_id]["backfilled"] += 1

			# Add an 'E' to the name of encrypted rooms
			room_name = "E " if current_room.encrypted else ""
			room_name += rfa(current_room.display_name)

			# Enter 		-> Read messages in room
			# Right arrow 	-> Write message to room
			menu_contents.append([
				room_name,
				lambda x=current_room: self.display_messages(x),
				lambda x=current_room: self.write_message(x)
			])

		menu_contents.append(["Settings", self.show_settings])
		Menu(menu_contents, self.i, self.o, name="Matrix app main menu").activate()

	def show_settings(self):
		mc = [["Log out", self.logout]]
		Menu(mc, self.i, self.o, catch_exit=False, name="Matrix app settings menu").activate()

	def logout(self):
		self.config["token"] = ''
		self.config["username"] = ''
		self.save_config()
		raise MenuExitException

	# Creates a new screen with an Input to write a message
	def write_message(self, room):
		message = UniversalInput(self.i, self.o, message="Message", name="Matrix app message input").activate()
		if message is None:
			return False

		# Send the message to the room and display it for a short amount of time
		room.send_text(message)

	# Display all messages of a specific room
	def display_messages(self, room):
		room_name = rfa(room.display_name)
		logger.debug(u"Viewing room: {}".format(room_name))

		# Set the currently active room to this room, important for adding messages and refreshing the menu
		self.active_room = room.room_id

		cb = lambda x=room: self._handle_messages_top(x)

		# Create a menu to display the messages
		self.messages_menu = MessagesMenu(self._get_messages_menu_contents(room.room_id), self.i, self.o, name="Matrix MessageMenu for {}".format(room_name),
			entry_height=1, load_more_callback=lambda x=room: self._handle_messages_top(x))

		self.messages_menu.activate()

	# Displays a single message fully with additional information (author, time)
	def display_single_message(self, msg, author, unix_time):
		full_msg = "{0}\n{1}\n\n".format(strftime("%m-%d %H:%M", localtime(unix_time / 1000)), rfa(author))

		for line in wrap(msg, self.o.cols):
			full_msg += rfa(line)
			full_msg += "\n"

		TextReader(full_msg, self.i, self.o, name="Matrix message display menu").activate()

	# Used as callback for the room listeners
	def _on_message(self, room, event):
		if event["event_id"] in self.seen_events:
			logger.debug("Event {} seen, ignoring".format(event["event_id"]))
			return
		self.seen_events.append(event["event_id"])
		logger.debug(u"New event: {}".format(event['type']))
		event_type = event.get('type', "not_a_defined_event")
		# Check if a user joined the room
		if event_type == "m.room.member":
			content = event.get('content', {})
			if event.get('membership', None) == "join":

				self._add_new_message(room.room_id, {
						'timestamp': event.get('origin_server_ts', 0),
						'type': event.get('type', 'unknown_type'),
						'sender': unicode(rfa(event.get('sender', 'unknown_sender'))),
						'content': rfa(unicode("+ {}").format(content.get('displayname', ''))),
						'id': event.get('event_id', 0)
					})

		# Check for new messages
		elif event_type == "m.room.message":
			content = event.get('content', {})
			if content.get('msgtype', None) == "m.text":
				prefix = ""
				if event.get('sender', None) == self.client.get_user().user_id or event.get("sender", None) in self.config["your_other_usernames"]:
					# Prefix own messages with a '*'
					prefix = "* "

				self._add_new_message(room.room_id, {
						'timestamp': event.get('origin_server_ts', 0),
						'type': event.get('type', 'unknown_type'),
						'sender': unicode(rfa(event.get('sender', 'unknown_sender'))),
						'content': unicode(prefix + rfa(content.get('body', ''))),
						'id': event.get('event_id', 0)
					})

		elif event_type == "not_a_defined_event":
			logger.warning("Unknown event: {}".format(event))

		# Update the current view if required
		if self.active_room == room.room_id:
			self.messages_menu.set_contents(self._get_messages_menu_contents(room.room_id))
			self.messages_menu.refresh()
		# Setting flag - if not already set
		if not self.has_processed_new_events.isSet():
			logger.debug("New event processed, setting flag")
		self.has_processed_new_events.set()

	def _add_new_message(self, room_id, new_message):
		# Check whether it's a duplicate - shouldn't trigger because of the deduplication
		for m in self.stored_messages[room_id]['events']:
			if m['id'] == new_message['id']:
				logger.error("Message ID check triggered despite deduplication")
				return

		self.stored_messages[room_id]['events'].append(new_message)

	# Uses stored_messages to create a suitable list of menu entries for MessagesMenu
	def _get_messages_menu_contents(self, room_id):
		# Sort messages by their timestamp
		sorted_messages = sorted(self.stored_messages[room_id]['events'], key=lambda k: k['timestamp'])

		menu_contents = []

		for message in sorted_messages:
			content = rfa(message["content"])
			menu_contents.append([content, lambda c=content, s=rfa(message['sender']), t=message['timestamp']: self.display_single_message(c, s, t)])

		return menu_contents

	# Callback for MessagesMenu
	def _handle_messages_top(self, room):
		messages_to_load = 5
		self.has_processed_new_events.clear()
		try:
			room.backfill_previous_messages(limit=self.stored_messages[room.room_id]["backfilled"]+messages_to_load, reverse=True, num_of_messages=messages_to_load)
			self.stored_messages[room.room_id]["backfilled"] += messages_to_load
		except:
			logger.exception("Couldn't load previous messages!")
			return False
		else:
			if self.has_processed_new_events.isSet():
				self.has_processed_new_events.clear()
				return True
			return False
