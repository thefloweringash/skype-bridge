# Skype to IRC bridge

import sys
import Skype4Py
import irclib
import threading

DEBUG_VERBOSE = True
def debug(str):
    if DEBUG_VERBOSE:
        print str

# There is one skype instance, and one IRC instance per client
# To make a bridge, we create and connect an irc instance for the irc channel,
# then call SkypeClient.bridgeChatToIRC(chatName, ircInstance)

# skype

class SkypeClient:
    def __init__(self):
        self.channels = {}
        self.skype = Skype4Py.Skype(Transport='x11')
        self.skype.OnAttachmentStatus = lambda s: self.onSkypeAttach(s)
        self.skype.OnMessageStatus = lambda m, s: self.onSkypeMessageStatus(m, s)

    def connect(self):
        print 'Connecting to Skype...'
        self.skype.Attach()
        print 'Connected to Skype.'

    def onSkypeAttach(self, status):
        debug('API attachment status: ' + self.skype.Convert.AttachmentStatusToText(status))
        if status == Skype4Py.apiAttachAvailable:
            self.skype.Attach()

    def onSkypeMessageStatus(self, Message, Status):
        debug("Status from skype %s/%s Status==%s" % (Message.FromDisplayName, Message.Body, Status))
        if Status == 'RECEIVED': # or Status == 'SENT':
            chatName = Message.Chat.Name
            if(self.channels[chatName] is not None):
                debug("Dispatched to IRCClient")
                self.channels[chatName].sendUserMessage(Message.FromDisplayName, Message.Body)
            else:
                print "Ignored message from unassociated Skype chat %s" % chatName
        else:
            debug("Ignored (type)")

    def bridgeChatToIRC(self, chatName, ircChannel):
        self.channels[chatName] = ircChannel
        ircChannel.setSkypeChat(SkypeClient.SkypeChat(self.skype, chatName))

    # Object to be passed to the IRC instance to encapsulate communicating with a particular skype chat
    class SkypeChat:
        def __init__(self, skype, chatName):
            self.skype = skype
            self.chatName = chatName

        def sendUserMessage(self, user, message):
            debug("Passed message into Skype %s: <%s> %s" % (self.chatName, user, message))
            self.skype.Chat(self.chatName).SendMessage("%s: %s" % (user, message))


# irc.  Currently one connection per channel, a future optimisation
# would be to separate the IRC server connections from the channels

class IrcChannelClient(irclib.SimpleIRCClient):
    def __init__(self, host, nick):
        irclib.SimpleIRCClient.__init__(self)
        self.host = host
        self.nick = nick
        self.channels = {}

    def on_welcome(self,c,e):
        print "Welcomed to %s!" % self.host

    def on_pubmsg(self,c,e):
        channel = self.channels.get(e.target().lower())
        if channel:
            channel.on_pubmsg(c, e)
        else:
            debug("Ignoring message from irc: %s %s %s" % (
                    e.source(), e.target(), e.arguments()))

    def channel(self, name):
        name = name.lower()
        print "Joining %s" % name
        self.connection.join(name)
        channel = IrcChannelClient.Channel(self.connection, name)
        self.channels[name] = channel
        return channel

    def run(self):
        self.ircobj.process_forever()

    def connect(self):
        irclib.SimpleIRCClient.connect(self, self.host, 6667, self.nick)
        threading.Thread(None, lambda: self.run()).start()


    class Channel(object):
        def __init__(self, connection, name):
            self.connection = connection
            self.name = name

        def setSkypeChat(self, skypeChat):
            self.skypeChat = skypeChat

        def on_pubmsg(self, c, e):
            user = e.source()
            user = user[0:user.index('!')]
            message = e.arguments()[0]
            debug("Message from IRC: <%s> %s" % (user, message))
            if self.skypeChat is not None:
                debug("Dispatched to SkypeChat")
                self.skypeChat.sendUserMessage(user, message)
            else:
                print "Channel %s not bridged to skype, discarded message" % (self.channel)
        def sendUserMessage(self, user, message):
            debug("Passed message to IRC channel: %s <%s> %s" %(self.channel, user, message))
            self.connection.privmsg(self.channel, "%s: %s" % (user, message))


# we maintain a one to one mapping of IRC channels to skype chats

skypeInstance = SkypeClient()
skypeInstance.connect()

ircSitharus = IrcChannelClient("irc.sitharus.com", "lskype")
ircSitharus.connect()
skypeInstance.bridgeChatToIRC("#chris.andreae/$b81041707fc653fb",
                              ircSitharus.channel("#wellingtonlunchchat"))

skypeInstance.bridgeChatToIRC("#chris.andreae/$c301b64f21991556",
                              ircSitharus.channel("#flood"))


print "Unblocked, manual loop"
Cmd = ''
while not Cmd == 'exit':
    Cmd = raw_input('')
