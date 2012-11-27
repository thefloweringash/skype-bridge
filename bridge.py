# Skype to IRC bridge

import sys
import Skype4Py
import irclib
import threading
import re
import random
import time
import traceback

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
        self.skype.OnNotify = lambda n: self.onSkypeNotify(n)
        self.skype.OnChatMembersChanged = lambda n: debug("chat members changed")
        self.connect()

    def connect(self):
        print 'Connecting to Skype...'
        self.skype.Attach()
        print 'Connected to Skype.'

    def onSkypeNotify(self, notification):
        #debug('Received low level skype notify: %s' % notification)
        type, b = Skype4Py.utils.chop(notification)
        if type == 'CHATMESSAGE':
            object_id, prop_name, value = Skype4Py.utils.chop(b, 2)
            message = Skype4Py.skype.ChatMessage(self.skype, object_id)
            ## when a message is edited, we get a sequence of edited_timestamp/edited_by/body CHATMESSAGE messages. 
            ## these cause the underlying ChatMessage object to be altered, so all we need to do is snag the notification
            ## for the last of the sequence (BODY), and fire off an edit notification.

            ## Unfortunately we can't use the updated value for the
            ## message in the ChatMessage object, since those won't
            ## be updated until this message is *processed*, which
            ## occurs after this hook.  The value field in this
            ## notification should be good enough though

            if prop_name == 'BODY':  
                editor = message.EditedBy 
                sender = message.FromDisplayName
                chatName = message.Chat.Name
                messageBody = value #message.Body
                sendMessage =  "[edited by %s] %s" % (editor, messageBody)
                if self.channels.get(chatName) is not None:
                    debug("Dispatched edit from skype instance to chat endpoint")
                    self.channels[chatName].pushUserMessage(sender, sendMessage)
                        

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
    def __init__(self, host, nick, password):
        irclib.SimpleIRCClient.__init__(self)
        self.host = host
        self.nick = nick
        self.password = password
        self.channels = {}
        self.connectServer()

    def on_welcome(self,c,e):
        print "Welcomed to %s, ready to join!" % (self.host)
        if self.password != None:
            self.connection.privmsg("nickserv", "identify %s" % self.password)
        for channelName in self.channels.keys():
            print "Re-joining channel: %s" % (channelName)
            self.connection.join(channelName)

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
        self.dispatch_message(channelName, "emote", "%s %s" % (user, message))

    def dispatch_message(self, channelName, user, message):
        channel = self.channels.get(channelName)
        if channel:
            debug("pushing message")
            channel.pushUserMessage(user, message)
        else:
            print "Ignoring message, no channel"
    
    def on_ctcp(self,c,e):
        if e.arguments()[0] != 'ACTION':
            self.print_debug("CTCP message", c, e)


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
        channelName = e.target().lower()
        user = self.get_user(e.source())
        self.channels.get(channelName).pushUserMessage("irc", "%s has left" % user)

    def on_join(self,c,e):
        channelName = e.target().lower()
        user = self.get_user(e.source())
        self.channels.get(channelName).pushUserMessage("irc", "%s has joined" % user)

    def on_invite(self, c, e):
        print "Invite to %s received from %s" % (e.arguments()[0],  e.source())
        self.connection.join(e.arguments()[0])

    def on_inviteonlychan(self, c, e):
        print "Channel %s is invite-only, requesting invitation from chanserv.." % (e.arguments()[0])
        self.connection.privmsg("chanserv", "invite %s" % (e.arguments()[0]))

    def print_debug(self, name, c, e):
        print "event %s received: c is %s\ne.target is %s\ne.source is %s\n" % (name, c, e.target(), e.source())
        for i in range(0,len(e.arguments())):
            print "e.arguments[%d] is %s\n" % (i, e.arguments()[i])

    def connectServer(self):
        print "Connecting to irc server %s.."%self.host
        self.connect(self.host, 6667, self.nick)
        threading.Thread(None, lambda: self.process_forever_with_catch()).start()
        threading.Thread(None, lambda: self.maintain_server_connection()).start()
    
    def process_forever_with_catch(self):
        while True:
            try:
                self.ircobj.process_forever()
            except Exception:
                print "Exception in irc process_forever, retrying"
                print traceback.format_exc()
    
    def maintain_server_connection(self):
        print "Running server connection check"
        while True:
            try:
                time.sleep(20)
                self.connection.ping(self.nick)  # lazy: why check for pong, when it lets me know it's disconnected
            except irclib.ServerConnectionError:
                print "Disconnect detected, reconnecting to IRC server.."
                try:
                    self.connect(self.host, 6667, self.nick)
                except irclib.ServerConnectionError:
                    print "Could not reconnect, looping"

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
            chunk_size = 415 - len(user) - 4;  # trial and error, probably server specific
            for line in message.split("\n"):
                length = len(line);
                off = 0;
                while off < length:
                    step = min(chunk_size, (length - off))
                    chunk = line[off : (off + step)]
                    off += step

                    enc_chunk = u"%s: %s" % (user, chunk)
                    safe_chunk = enc_chunk.encode("utf-8", "replace")
                    self.server.sendMessageToChannel(self.channelName, safe_chunk)

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
                s = IRCClient(server, nick, params.get("password"))
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
