# Skype to IRC bridge

import sys
import Skype4Py
import irclib
import threading

DEBUG_VERBOSE = True
def debug(str):
    if DEBUG_VERBOSE:
        print str


class BridgeEndPoint:
    def __init__(self):
        self.endpoint = None

    def setEndPoint(self, endpoint):
        self.endpoint = endpoint
    
    def pushUserMessage(self, user, message):
        if(self.endpoint):
            debug("pushed message to remote end point")
            self.endpoint.receiveUserMessage(user, message)
        else:
            print "Warning, discarded message on unconnected end point: %s" % self.description()

    def description(self):
        return "abstract base end point"

    def receiveUserMessage(self, user, message):
        raise Exception("Called abstract base end point receive")

    def Bridge(end1, end2):
        end1.setEndPoint(end2)
        end2.setEndPoint(end1)


# There is one skype instance.  We can get chat end points by calling its getChat method
# with the id of the skype chat
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
            if self.channels.get(chatName) is not None:
                debug("Dispatched from skype instance to chat endpoint")
                self.channels[chatName].pushUserMessage(Message.FromDisplayName, Message.Body)
            else:
                print "Ignored message from unassociated Skype chat %s" % chatName
        else:
            debug("Ignored (type)")

    def getChat(self, chatName):
        channel = SkypeClient.SkypeChat(self.skype, chatName)
        self.channels[chatName] = channel
        return channel

    # Object to be passed to the IRC instance to encapsulate communicating with a particular skype chat
    class SkypeChat(BridgeEndPoint):
        def __init__(self, skype, chatName):
            BridgeEndPoint.__init__(self)
            self.skype = skype
            self.chatName = chatName

        def receiveUserMessage(self, user, message):
            debug("Passed message into Skype %s: <%s> %s" % (self.chatName, user, message))
            self.skype.Chat(self.chatName).SendMessage("%s: %s" % (user, message))

        def description(self):
            "Skype chat %s" % self.chatName


# irc.  Currently one connection per channel, a future optimisation
# would be to separate the IRC server connections from the channels

class IrcChannelClient(irclib.SimpleIRCClient, BridgeEndPoint):
    def __init__(self, host, channel, nick):
        irclib.SimpleIRCClient.__init__(self)
        BridgeEndPoint.__init__(self)
        self.host = host
        self.channel = channel.lower()
        self.nick = nick

    def on_welcome(self,c,e):
        print "Welcomed to %s, joining %s!" % (self.host, self.channel)
        c.join(self.channel)
        print "Joined!"

    def on_pubmsg(self,c,e):
        user = e.source()
        user = user[0:user.index('!')]
        message = e.arguments()[0]
        debug("Message from IRC: <%s> %s" % (user, message))
        self.pushUserMessage(user, message)

    def run(self):
        self.ircobj.process_forever()

    def connectChannel(self):
        self.connect(self.host, 6667, self.nick)
        threading.Thread(None, lambda: self.run()).start()

    def receiveUserMessage(self, user, message):
        if self.connection is not None:
            debug("Passed message to IRC channel: %s <%s> %s" %(self.channel, user, message))
            self.connection.privmsg(self.channel, "%s: %s" % (user, message))
        else:
            print "IRC Client not connected"

    def description(self):
        return "IRC channel %s on %s" % (self.channel, self.host)

# we maintain a one to one mapping of IRC channels to skype chats

skypeInstance = SkypeClient()
skypeInstance.connect()

skypeChat = skypeInstance.getChat("#chris.andreae/$b81041707fc653fb")

ircChannel = IrcChannelClient("irc.sitharus.com", "#wellingtonlunchchat", "cskype2")
ircChannel.connectChannel()

BridgeEndPoint.Bridge(skypeChat, ircChannel)

print "Unblocked, manual loop"
Cmd = ''
while not Cmd == 'exit':
    Cmd = raw_input('')
