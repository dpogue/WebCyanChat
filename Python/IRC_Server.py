from Logger import *
from Utils import *
from HTTP_Server import HTTP_Server

import threading
import socket

class IRC_Server:
	# max name length is 9 characters
	class IRC_Message:
		def __init__(self, message):
			self.prefix = str()
			self.command = str()
			self.params = list()
			self.trail = str()
			args = message.split(' ')
			args.reverse()
			if(message.startswith(':')): 
				# the prefix, if present, indicates the origin of the message
				self.prefix = args.pop()[0:]
			# a command is required for all messages
			self.command = args.pop()
			while(len(args) > 0 and not args[-1].startswith(':')):
				# command parameters
				self.params.append(args.pop())
			# and any characters following a ':' are trailing chars
			args.reverse()
			self.trail = ' '.join(args)[1:]

		def toString(self):
			out = str()
			if(self.prefix != ""):
				out += ":%s " % self.prefix
			out += "%s " % self.command
			for param in self.params:
				out += "%s " % param
			if(self.trail != ""):
				out += ":%s" % self.trail
			return out


	class IRC_Connection:
		# type flags
		UNKNOWN = 0
		CLIENT = 1
		SERVER = 2

		def __init__(self, sock, addr):
			self.comLock = threading.Lock()
			self.type = self.UNKNOWN
			self.sock = sock
			self.addr = addr
			self.password = str()
			self.user = None # this remains None for servers
					 # and is set for locally connected clients

		def send(self, message):
                        self.comLock.acquire()
                        try:
                                log(self, "sending: %s to %s" % (repr(message), self), 2)
                                self.sock.send(message + "\r\n")
                        except:
                                log(self, "send error to: %s" % self, 2)
                        self.comLock.release()

	class IRC_User:
		def __init__(self, connection, user="", hopcount = 0):
			args = user.split("!")
			self.nick = args[0]
			if(len(args) == 2):
				args = args[1].split("@")
				self.username = args[0]
			if(len(args) == 2):
				self.hostname = args[1]
			self.realname = str()
			self.servername = str()
			self.flags = ""
			self.hopcount = hopcount
			# this is either the connection to the client
			# or the connection to the server the client is
			# connected to us through
			self.connection = connection
			# a list of channel objects which the user is 
			# subscribed to
			self.channels = list()
		
		def fullUser(self):
			return "%s!%s@%s" % (self.nick, self.username, self.hostname)
	
	class IRC_Server:
		def __init__(self, connection, hostname):
			self.connection = connection
			self.hostname = hostname
	
	class IRC_Channel:
		class Channel_User:
			def __init__(self, user):
				self.user = user
				self.flags = ""

			def toString(self):
				sigil = ""
				if(self.flags.find("v") != -1):
					sigil = "+"
				if(self.flags.find("o") != -1):
					sigil = "@"
				return sigil + self.user.nick
			
		def __init__(self, name):
			self.name = name
			self.topic = str()
			self.flags = ""
			self.users = list()

		def addUser(self, user):
			self.users.append(self.Channel_User(user))
			user.channels.append(self)

		def removeUser(self, user):
			for cuser in self.users:
				if(cuser.user == user):
					self.users.remove(cuser)
					break
			user.channels.remove(self)

		def broadcast(self, msg, exclude=None):
			connections = list()
			for cuser in self.users:
				if((not cuser.user.connection in connections) and connection != exclude):
					connections.append(cuser.user.connection)
			for connection in connections:
				connection.send(msg.toString())
	
	def __init__(self):
		self.quit = threading.Event()
		self.broadcastLock = threading.Lock()
		self.accessLock = threading.Lock()
		self.hostname = "localhost"
		# prefs
		self.prefs = { \
			"irc_port": 6667, \
		}
		# irc servers need to know a lot of stuff
		self.connections = list()
		self.users = list()
		self.servers = list()
		self.channels = list()

	def findUser(self, nick):
		nick = nick.split("!")[0]
		for user in self.users:
			if(user.nick == nick):
				return user
		return None

	def findChannel(self, name):
		for channel in self.channels:
			if(channel.name == name):
				return channel
		return None

	def removeUser(self, user):
		# perform all the cleanup that needs to be done to get a user out of the system
		self.connections.remove(user.connection)
		self.users.remove(user)
		for channel in user.channels:
			channel.removeUser(user)
		if(user.connection.type == self.IRC_Connection.CLIENT):
			user.connection.sock.close()
			self.connections.remove(user.connection)

	def start(self):
		acceptThread = threading.Thread(None, self.acceptLoop, "acceptLoop", (self.prefs["irc_port"],))
		acceptThread.setDaemon(1)
		acceptThread.start()
		self.run()

	def run(self):
		self.quit.wait()
	
	def acceptLoop(self, port=6667): #Threaded per-server
		listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		try:
			listener.bind(('', port))
		except:
			log(self, "failed to bind port %d" % port)
			self.quit.set()
			return
		log(self, "listening on port %d" % port)
		while 1:
			listener.listen(1)
			(sock, addr) = listener.accept()
			self.addConnection(sock, addr)

	def addConnection(self, sock, addr):
		newConnection = self.IRC_Connection(sock, addr)
		self.connections.append(newConnection)
		# the connection will be added to the list (either server or client) by the message handler
		sockThread = threading.Thread(None, self.sockLoop, "sockLoop", (newConnection,))
		sockThread.setDaemon(1)
		sockThread.start()

	def sockLoop(self, connection): #Threaded per-socket
		while 1:
			line = readTo(connection.sock, "\n", ['\r'])
			if(not line):
				log(self, "lost connection to %s" % connection, 2)
				return
			log(self, "received: %s from %s" % (line, connection), 2)
			self.handleMsg(connection, self.IRC_Message(line))

	def broadcast(self, msg, excludeConn=None, connType=None):
		self.broadcastLock.acquire()
		for connection in self.connections:
			if(connection != exclude and (connType == None or connType == connection.type)):
				connection.send(msg.toString())
		self.broadcastLock.release()

	def localBroadcast(self, msg, relUser):
		localUsers = list()
		for channel in relUser.channels:
			for cuser in channel.users:
				if((not cuser.user in localUsers) and cuser.user.connection.type == self.IRC_Connection.CLIENT):
					localUsers.append(cuser.user)
		for user in localUsers:
			user.connection.send(msg.toString())
	
	def handleMsg(self, connection, msg):
		log(self, "command: %s from %s" % (msg.command, connection), 2)
		if(msg.command == "PASS"):
			connection.password = msg.params[0]
		elif(msg.command == "NICK"):
			if(connection.type == self.IRC_Connection.SERVER):
				user = self.findUser(msg.params[0])
				if(user):
					sender = msg.prefix
					msg.prefix = self.hostname
					msg.command = "KILL"
					msg.params = [msg.params[0]]
					# send a KILL to the server we received this from
					connection.send(msg.toString())
					# if this was a name change, we need to KILL both nicks
					if(sender):
						msg.params = [sender]
						self.broadcast(msg, connection, self.IRC_Connection.SERVER)
					# broadcast this to local clients which know about the user
					self.localBroadcast(msg)
					# get rid of the user
					self.removeUser(user)
					return
				hopcount = int(msg.params[1])
				if(msg.prefix):
					# name change
					user = self.findUser(msg.prefix)
					user.nick = msg.params[0]
				else:
					# new user
					self.users.append(self.IRC_User(connection, nick, hopcount))
				# increment the hopcount and forward to servers
				msg.params[1] = str(hopcount + 1)
				self.broadcast(msg, connection, self.IRC_Connection.SERVER)
				# forward the nick msg to local users who need to know
				msg.params.remove(msg.params[1])
				self.localBroadcast(msg, user)
			elif(connection.type == self.IRC_Connection.CLIENT):
				if(self.findUser(msg.params[0])):
					# check that nobody's taken the nick already
					connection.send(ERR_NICKCOLLISION)
					return
				# get this connections previous username and set it as the sender of the nick msg
				msg.prefix = connection.user.fullUser()
				# forward the nick msg to the servers
				msg.params.append("0")
				self.broadcast(msg, None, self.IRC_Connection.SERVER)
				# now we can change the name of the user locally
				connection.user.nick = msg.params[0]
				# forward the nick msg to local users who need to know
				msg.params.remove(msg.params[1])
				self.localBroadcast(msg, connection.user)
			elif(connection.type == self.IRC_Connection.UNKNOWN):
				# now we know it's a client
				connection.type = self.IRC_Connection.CLIENT
				connection.user = self.IRC_User(connection, msg.params[0])
				self.users.append(connection.user)
				#msg.prefix = self.hostname
				connection.send(msg.toString())
		elif(msg.command == "USER"):
			# we should only recieve this from a user (client connection)
			connection.type = self.IRC_Connection.CLIENT
			connection.user = self.IRC_User(connection)
			connection.user.username = msg.params[0]
			connection.user.hostname = msg.params[1]
			connection.user.servername = msg.params[2]
			connection.user.realname = msg.trail
			if(connection.user.nick):
				# now we can send the user to the servers
				nickMsg = self.IRC_Message("NICK")
				nickMsg.prefix = self.hostname
				nickMsg.params = [connection.user.nick]
				self.broadcast(nickMsg, None, self.IRC_Connection.SERVER)
				userMsg = self.IRC_Message("USER")
				userMsg.prefix = user.nick
				userMsg.params = [user.username, user.hostname, user.servername]
				userMsg.trail = user.realname
				self.broadcast(usrMsg, None, self.IRC_Connection.SERVER)
		elif(msg.command == "SERVER"):
			pass
		elif(msg.command == "OPER"):
			pass
		elif(msg.command == "QUIT"):
			if(connection.type == self.IRC_Connection.CLIENT):
				msg.prefix = connection.user.fullUser()
			self.removeUser(self.findUser(msg.prefix))
			self.broadcast(msg, connection)
		elif(msg.command == "SQUIT"):
			pass
		elif(msg.command == "JOIN"):
			for chanName in msg.params[0].split(","):
				channel = self.findChannel(chanName)
				if(not channel):
					channel = IRC_Channel(chanName)
					self.channels.append(channel)
				msg.params[0] = chanName
				channel.addUser(self.findUser(msg.prefix))
				if(connection.type == self.IRC_Connection.CLIENT):
					msg.prefix = connection.user.fullUser()
					channel.broadcast(msg)
				else:
					channel.broadcast(msg, connection)
			if(connection.type == self.IRC_Connection.CLIENT):
				# this is a local user, we must send them all the stuff (like topic, userlist)
				# first send the channel topic
				if(channel.topic):
					msg = self.IRC_Message("332") # RPL_TOPIC
					msg.trail = channel.topic
				else:
					msg = self.IRC_Message("331 :No topic is set") # RPL_NOTOPIC
				msg.prefix = self.hostname
				msg.params = [channel.name]
				connection.send(msg.toString())
				# Now send the channel userlist
				msg = self.IRC_Message("353") # RPL_NAMEREPLY
				msg.prefix = self.hostname
				msg.params = [channel.name]
				for cuser in channel.users:
					msg.trail = cuser.toString()
					connection.send(msg.toString())
				msg = self.IRC_Message("366 :End of /NAMES list") # RPL_ENDOFNAMES
				msg.prefix = self.hostname
				msg.params = [channel.name]
				connection.send(msg.toString())
		elif(msg.command == "PART"):
			for chanName in msg.params[0].split(","):
				channel = self.findChannel(chanName)
				msg.params[0] = chanName
				if(connection.type == self.IRC_Connection.CLIENT):
					msg.prefix = connection.user.fullUser()
					channel.broadcast(msg)
				else:
					channel.broadcast(msg, connection)
				channel.removeUser(self.findUser(msg.prefix))
		elif(msg.command == "MODE"):
			if(len(msg.params) == 1):
				# user is requesting modes
				if(msg.params[0].startswith("#") or msg.params[0].startswith("&")):
					channel = self.findChannel(msg.params[0])
					# now send the channel modes
					msg = self.IRC_Message("324") # RPL_CHANNELMODEIS
					msg.prefix = self.hostname
					msg.params = [channel.name, "+" + channel.flags]
					connection.send(msg.toString())
				else:
					user = self.findUser(msg.params[0])
					msg = self.IRC_Message("221") # RPL_UMODEIS
					msg.prefix = self.hostname
					msg.params = [user.nick, "+" + user.flags]
			elif(len(msg.params) > 1):
				# user is trying to change a mode
				if(msg.params[0].startswith("#") or msg.params[0].startswith("&")):
					# channel mode being set
					channel = self.findChannel(msg.params[0])
					
					# forward the message
					msg.prefix = connection.user.fullUser()
					channel.broadcast(msg)
				else:
					# user mode being set
					user = self.finduser(msg.params[0])
					if(msg.params[1].startswith("+")):
						# add modes
						for flag in msg.params[1][1:]:
							if(user.flags.find(flag) == -1):
								user.flags += flag
					elif(msg.params[1].startswith("-")):
						# remove modes
						for flag in msg.params[1][1:]:
							user.flags = user.flags.replace(flag, "")
		elif(msg.command == "TOPIC"):
			channel = self.findChannel(msg.params[0])
			if(msg.trail):
				channel.topic = msg.trail
				msg.prefix = connection.user.fullUser()
				channel.broadcast(msg)
			else:
				# first send the channel topic
				if(channel.topic):
					msg = self.IRC_Message("332") # RPL_TOPIC
					msg.trail = channel.topic
				else:
					msg = self.IRC_Message("331 :No topic is set") # RPL_NOTOPIC
				msg.prefix = self.hostname
				msg.params = [channel.name]
				connection.send(msg.toString())
		elif(msg.command == "NAMES"):
			pass
		elif(msg.command == "LIST"):
			pass
		elif(msg.command == "INVITE"):
			pass
		elif(msg.command == "KICK"):
			pass
		elif(msg.command == "VERSION"):
			pass
		elif(msg.command == "STATS"):
			pass
		elif(msg.command == "LINKS"):
			pass
		elif(msg.command == "TIME"):
			pass
		elif(msg.command == "CONNECT"):
			pass
		elif(msg.command == "TRACE"):
			pass
		elif(msg.command == "ADMIN"):
			pass
		elif(msg.command == "INFO"):
			pass
		elif(msg.command == "PRIVMSG"):
			if(connection.type == self.IRC_Connection.CLIENT):
				msg.prefix = connection.user.fullUser()
			for target in msg.params[0].split(","):
				# hopefully this doesn't count as modifying the iterable
				msg.params[0] = target
				if(target.startswith("#") or target.startswith("&")):
					self.findChannel(target).broadcast(msg)
				else:
					self.findUser(target).connection.send(msg.toString())
		elif(msg.command == "NOTICE"):
			if(connection.type == self.IRC_Connection.CLIENT):
				msg.prefix = connection.user.fullUser()
			for target in msg.params[0].split(","):
				# hopefully this doesn't count as modifying the iterable
				msg.params[0] = target
				if(target.startswith("#") or target.startswith("&")):
					self.findChannel(target).broadcast(msg)
				else:
					self.findUser(target).connection.send(msg.toString())
		elif(msg.command == "WHO"):
			# Now send the channel userlist
			for target in msg.params[0]:
				if(target.startswith("#") or target.startswith("&")):
					channel = self.findChannel(target)
					msg = self.IRC_Message("352") # RPL_WHOREPLY
					msg.prefix = self.hostname
					for cuser in channel.users:
						user = cuser.user
						msg.params = [channel.name, user.hostname, user.server, user.nick, [H, G], "*@+"]
						msg.trail = "%d %s" % (user.hopcount, user.realname)
						connection.send(msg.toString())
					msg = self.IRC_Message("315 :End of /WHO list") # RPL_ENDOFWHO
					msg.prefix = self.hostname
					msg.params = [channel.name]
					connection.send(msg.toString())
				else:
					user = self.findUser(target)
					msg.prefix = self.hostname
					msg.params
		elif(msg.command == "WHOIS"):
			pass
		elif(msg.command == "WHOWAS"):
			pass
		elif(msg.command == "KILL"):
			self.broadcast(msg, connection)
			user = self.findUser(msg.prefix)
			self.removeUser(user)
		elif(msg.command == "PING"):
			pass
		elif(msg.command == "PONG"):
			pass
		elif(msg.command == "ERROR"):
			pass
				
