# Skype to IRC bridge

import sys
import Skype4Py
import irclib
import threading
import re
import random

DEBUG_VERBOSE = True
def debug(str):
    if DEBUG_VERBOSE:
        print str


class BridgeEndPoint(object):
    def __init__(self):
        super(BridgeEndPoint,self).__init__()
        self.otherEnd = None

    def setEndPoint(self, endpoint):
        self.otherEnd = endpoint
    
    def pushUserMessage(self, user, message):
        if(self.otherEnd):
            debug("pushed message to remote end point")
            self.otherEnd.receiveUserMessage(user, message)
        else:
            print "Warning, discarded message on unconnected end point: %s" % self.description()

    def description(self):
        return "abstract base end point"

    def receiveUserMessage(self, user, message):
        raise Exception("Called abstract base end point receive")

    def destroy(self):
        print "Warning: destroyed abstract base"

    def Bridge(end1, end2):
        end1.setEndPoint(end2)
        end2.setEndPoint(end1)

    def Unbridge(end1, end2):
        end1.setEndPoint(None)
        end2.setEndPoint(None)

# A filter endpoint wraps another endpoint, and permits filtering (modifying or swallowing)
# incoming or outgoing messages.  Override filter_incoming/filter_outgoing, in subclasses,
# return either new (user,message) tuple or null to eat the message
class Filter:
    def filter_incoming(self, user, message, ep):
        return (user, message)

    def filter_outgoing(self, user, message, ep):
        return (user, message)


class FilteringEndPoint(BridgeEndPoint):
    def __init__(self):
        BridgeEndPoint.__init__(self)
        self.filters = []

    def receiveUserMessage(self, user, message):
        keep = True;
        for filter in self.filters:
            filtered = filter.filter_incoming(user, message, self)
            if filtered:
                (user, message) = filtered
            else:
                keep = False;
                break
        if keep:
            self.receiveUserMessageImpl(user, message)

    def receiveUserMessageImpl(self, user, message):
        raise Exception("Called abstract base receive");

    def pushUserMessage(self, user, message):
        keep = True;
        for filter in self.filters:
            filtered = filter.filter_outgoing(user, message, self)
            if filtered:
                (user, message) = filtered
            else:
                keep = False;
                break
        if keep:
            super(FilteringEndPoint, self).pushUserMessage(user, message)

    def addFilter(self, filter):
        self.filters.append(filter)


#example
class IRCHighlightFilter(Filter):
    def __init__(self, hilites):
        self.hilites = hilites

    def filter_incoming(self, user, message, ep):
        for hilit in self.hilites:
            message = message.replace(hilit, "%s"%hilit);
        return (user, message)

#more example
class RollingFilter(Filter):
    def filter_outgoing(self, user, message, ep):
        print "into outgoing filter: %s and %s" % (user, message)
        if re.match("/roll", message):
            r = random.randint(1,100)
            m = "%s rolls: %s" % (user, r)
            ep.receiveUserMessageImpl("dice", m)
            return ("dice", m) # and push
        else:
            return (user, message)

    def filter_incoming(self, user, message, ep):
        print "into incoming filter: %s and %s" % (user, message)
        if re.match("\s*/roll", message):
            r = random.randint(1,100)
            m = "%s rolls: %s" % (user, r)
            ep.pushUserMessage("dice", m)
            return ("dice", m) # and receive
        else:
            return (user, message)

# There is one skype instance.  We can get chat end points by calling its getChat method
# with the id of the skype chat
class SkypeClient:
    def __init__(self):
        self.channels = {}
        self.skype = Skype4Py.Skype(Transport='x11')
        self.skype.OnAttachmentStatus = lambda s: self.onSkypeAttach(s)
        self.skype.OnMessageStatus = lambda m, s: self.onSkypeMessageStatus(m, s)
        self.connect()

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
            debug("Ignored message by type: %s" % (Status))

    def getChat(self, chatName):
        channel = self.channels.get(chatName)
        if not channel:
            channel = SkypeClient.SkypeChat(self, self.skype, chatName)
            self.channels[chatName] = channel
        return channel

    def removeChat(self, chatName):
        self.channels[chatName] = None

    # Object to be passed to the IRC instance to encapsulate communicating with a particular skype chat
    class SkypeChat(FilteringEndPoint):
        def __init__(self, skypeClient, skype, chatName):
            FilteringEndPoint.__init__(self)
            self.skypeClient = skypeClient
            self.skype = skype
            self.chatName = chatName

        def receiveUserMessageImpl(self, user, message):
            debug("Passed message into Skype %s: <%s> %s" % (self.chatName, user, message))
            self.skype.Chat(self.chatName).SendMessage("%s: %s" % (user, message))

        def description(self):
            "Skype chat %s" % self.chatName

        def destroy(self):
            self.setEndPoint(None)
            self.skypeClient.removeChat(self.chatName)


# irc. 

class IRCClient(irclib.SimpleIRCClient):
    def __init__(self, host, nick):
        irclib.SimpleIRCClient.__init__(self)
        self.host = host
        self.nick = nick
        self.channels = {}
        self.connectServer()

    def on_welcome(self,c,e):
        print "Welcomed to %s, ready to join!" % (self.host)

    def get_user(self, s):
        return s[0:s.index('!')]

    def on_pubmsg(self,c,e):
        channelName = e.target().lower()
        user = self.get_user(e.source())
        message = e.arguments()[0]
        debug("Message from IRC: %s | <%s> %s" % (channelName, user, message))
        self.dispatch_message(channelName, user, message)

    def on_action(self,c,e):
        channelName = e.target().lower()
        user = self.get_user(e.source())
        message = e.arguments()[0]
        debug("Message from IRC: %s | <%s> %s" % (channelName, user, message))
        self.dispatch_message(channelName, "emote", "%s %s" % (user, message));

    def dispatch_message(self, channelName, user, message):
        channel = self.channels.get(channelName)
        if channel:
            debug("pushing message")
            channel.pushUserMessage(user, message)
        else:
            print "Ignoring message, no channel"
    
    def on_ctcp(self,c,e):
        if e.arguments()[0] != 'ACTION':
            print "CTCP received: c is %s\ne.target is %s\ne.source is %s\n" % (c, e.target(), e.source())
            for i in range(0,len(e.arguments())):
                print "e.arguments[i] is %s\n" % (e.arguments()[i])


    def on_nick(self,c,e):
        old_user = self.get_user(e.source())
        new_user = e.target()
        for channel in self.channels.keys():
            self.channels.get(channel).pushUserMessage("nick", "%s is now known as %s" % (old_user, new_user))

    def on_quit(self,c,e):
        user = self.get_user(e.source())
        message = e.arguments()[0]
        for channel in self.channels.keys():
            self.channels.get(channel).pushUserMessage("irc", "%s has quit: %s" % (user, message))

    def on_part(self,c,e):
        user = self.get_user(e.source())
        for channel in self.channels.keys():
            self.channels.get(channel).pushUserMessage("irc", "%s has left" % user)

    def on_join(self,c,e):
        user = self.get_user(e.source())
        for channel in self.channels.keys():
            self.channels.get(channel).pushUserMessage("irc", "%s has joined" % user)


    def connectServer(self):
        print "Connecting to irc server %s.."%self.host
        self.connect(self.host, 6667, self.nick)
        threading.Thread(None, lambda: self.ircobj.process_forever()).start()
        
    def getChannel(self, channelName):
        channelName = channelName.lower()
        channel = self.channels.get(channelName)
        if not channel:
            self.connection.join(channelName) # actually connect to the channel
            print "Joined IRC channel %s" % channelName
            channel = IRCClient.IRCChannel(self, channelName)
            self.channels[channelName] = channel
        return channel

    def sendMessageToChannel(self, channelName, message):
        debug("Passed message into to IRC channel: %s %s" %(channelName, message))
        self.connection.privmsg(channelName, message)

    def removeChannel(self, channelName):
        self.connection.part(channelName)
        self.channels[channelName] = None
        # Todo: check size of channels hash, disconnect if empty

    class IRCChannel(FilteringEndPoint):
        def __init__(self, server, channelName):
            FilteringEndPoint.__init__(self)
            self.server = server
            self.channelName = channelName

        def receiveUserMessageImpl(self, user, message):
            for line in message.split("\n"):
                self.server.sendMessageToChannel(self.channelName, "%s: %s" % (user, line))

        def description(self):
            return "IRC channel %s on %s" % (self.channelName, self.server.host)
        
        def destroy(self):
            self.setEndPoint(None)
            self.server.removeChannel(self.channelName)



class BridgeManager:
    def __init__(self):
        # create and connect up our services
        self.skypeInstance = SkypeClient()
        self.ircServers = {}
    
    def createEndpoint(self, type, params):
        type = type.lower()
        if type == 'skype':
            return self.skypeInstance.getChat(params["chat"])  #todo: error handling for params
        elif type == 'irc':
            key = (server, nick) = (params["server"], params["nick"])
            s = self.ircServers.get(key)
            if not s:
                s = IRCClient(server, nick)
                self.ircServers[key] = s
            return s.getChannel(params["channel"])
        else:
            print "Unknown endpoint type"
            
    def bridge(self, a, b):
        BridgeEndPoint.Bridge(a, b)

    def unbridge(self, a, b):
        BridgeEndPoint.Unbridge(a, b)
        
m = BridgeManager()

skypeChat = m.createEndpoint('skype', {"chat": "#chris.andreae/$b81041707fc653fb"})
#skypeChat2 = m.createEndpoint('skype', {"chat": "#skype.irc.bridge/$andrew.childs.cons;18d2f66a4e56f2dd"})

ircChannel = m.createEndpoint("irc", {"server": "irc.sitharus.com","nick": "cskype", "channel": "#wellingtonlunchchat"})
#ircChannel2 = m.createEndpoint("irc", {"server": "irc.sitharus.com","nick": "cskype", "channel": "#bridgedev"})

#ircChannelx = m.createEndpoint("irc", {"server": "irc.sitharus.com","nick": "circ", "channel": "#bridgedev"})
#ircChannely = m.createEndpoint("irc", {"server": "irc.sitharus.com","nick": "circ", "channel": "#bridgedev2"})

#ircFilter = IRCHighlightFilterEndPoint(ircChannel2, ["chris", "lorne"])

rollingFilter = RollingFilter()
skypeChat.addFilter(rollingFilter)

bridge1 = m.bridge(skypeChat, ircChannel)

#bridge2 = m.bridge(skypeChat2, ircFilter)
#bridge3 = m.bridge(ircChannelx, ircChannely)

print "Unblocked, manual loop"
Cmd = ''
while not Cmd == 'exit':
    Cmd = raw_input('')
