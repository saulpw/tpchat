#!/usr/bin/python

from twisted.internet import reactor, protocol, defer, ssl
from twisted.python import log
from twisted.python.components import registerAdapter
from twisted.web.server import Site, NOT_DONE_YET, Session
from twisted.web.resource import Resource
from twisted.web.static import File
from twisted.web.util import Redirect

import twisted.protocols.basic
from zope.interface import Interface, Attribute, implements

import tpconfig

import sys
import time
import os
import re

verbose = False

divTimestampStart = '<table class="msg timestamp"><tr>' # to detect daily divisions
def divTimestamp(fileoffset):
    if fileoffset == 0:
        return divTimestampStart + '<td class="date"><span timet="%s" class="stardate">%s</span></td></tr></table>' % (getDateString(), time.strftime("%Y-%b-%d"))
    else:
        ahref = '<td class="date">'
        ahref += '<a class="stardate" timet="%s" href="javascript:get_backlog(%s)">%s</a>' % (getDateString(), fileoffset, time.strftime("%x"))
        ahref += '</td>' 
        return divTimestampStart + ahref + '</tr></table>'

fmtdivChatline = '''<table class="msg %(classes)s"><tr><td class="time" timet="%(time)s">%(hrmin)s</td> <td class="src"> %(src)s</td><td class="contents"> %(contents)s</td></tr></table>
''' # spaces included for reasonable cutnpaste, newline for chatlog

def divChatline(**extra):
    d = { 
      "time": getClockString(),
      "classes": "",
    }

    d.update(extra)

    d["hrmin"] = time.strftime("%H:%M", time.localtime(int(d["time"])))

    return fmtdivChatline % d

regexUrl = re.compile(r"(http://\S+)", re.IGNORECASE | re.LOCALE)

def getClockString():
    return int(time.time())

def getDateString():
    return getClockString()
#    return time.strftime("%Y %B %d %Z", time.gmtime())

class IUser(Interface):
    value = Attribute("user session")

class User(object):
    implements(IUser)
    def __init__(self, session):
        self.nick = ""
        self.channels = [ ]

registerAdapter(User, Session, IUser)

def isValidNick(nick):
    if len(nick) == 0:
        return False
    if nick in root.ircd.names:
        return False
    return True

class Channel(Resource):
    isLeaf = True
    def __init__(self, name, key=None):
        self.name = name
        self.logfn = os.path.join(tpconfig.log_path, self.name + ".log")
        self.listeners = { }
        self.key = key
        self.members = { }
        self.lastWriteTime = 0
        try:
            self.contents = file(self.logfn).read()
        except IOError:
            self.contents = ""

        root.ircd.join(name)
        if key is not None:
            root.ircd.setkey(name, key) 

    def __str__(self):
        return "[channel %s]" % self.name

    def debug(self):
        return "%s: %s listeners, %s bytes of content\n" % (self.name, len(self.listeners), len(self.contents))

    def logwrite(self, msg, fromIRC=False):
        data = ""

        lastWriteTime = self.lastWriteTime
        self.lastWriteTime = time.time()

        lastymd = time.gmtime(lastWriteTime)[0:3]
        nowymd = time.gmtime()[0:3]

        if lastymd != nowymd:
            data += divTimestamp(len(self.contents))

        data += msg

        self.contents += data

        with file(self.logfn, "a") as fp:
            fp.write(data)

        for member in self.listeners.keys():
            self.lpReply(member, data)

        self.listeners = { }

    def _reqFinished(self, failure, req):
        target = req.user.nick
        if target in self.listeners:
            del self.listeners[target]

         # XXX: how to avoid "Unhandled error in Deferred" messages?

    def render_GET(self, req):
        givent = -1

        try:
            givent = int(req.args["t"][0])
        except:
            pass

        if givent == -1:
            t = -len(self.contents)
        else:
            t = givent

        if t < 0:
            t = self.contents[:-t].rfind(divTimestampStart)
        else:
            t = self.contents[t:].find(divTimestampStart)

        if givent == -1 and t == -1:
            t = 0

        if t >= len(self.contents) or t == -1:
            self.listeners[req.user.nick] = req
            req.notifyFinish().addCallback(self._reqFinished, req)
            req.notifyFinish().addErrback(self._reqFinished, req)
            return NOT_DONE_YET

        history = self.contents[t:]
        history.replace("\n", "<br/>")

#        msg = '<head><link type="text/css" rel="stylesheet" href="style.css"/></head>'
        req.write(self.privateChatReply(history, timestamp=t))
        # render calls .finish() automatically
   
    def lpReply(self, target, text):
        if target in self.listeners:
            self.listeners[target].write(self.privateChatReply(text))
            self.listeners[target].finish()

    def lpDone(self, target):
        if target in self.listeners:
            self.listeners[target].finish()

    def privateChatReply(self, data, timestamp=None):
        tstxt = ""
        if timestamp:
            tstxt = 't="%s"' % timestamp
        return '<span %s nextt="%s" id="log">%s</span>' % (tstxt, len(self.contents)+1, data)
        
    def cmd_ME(self, src, rest):
        self.privmsg(src, "\001ACTION %s\001" % rest)

    def cmd_MSG(self, src, rest):
        target, msg = rest.split(" ", 1)
        if target in self.listeners:
            self.lpReply(target, divChatline(src="*%s*" % src, contents=msg, classes="private"))
        elif target in root.ircd.uids:
            root.ircd.PRIVMSG(target, src, msg)
        else:
            reply = "%s is not logged in (%s)" % (" ".join(self.listeners.keys()), target)
            return divChatline(src="***", contents=reply, classes="private")

        return divChatline(contents=msg, src="&#x2794;%s" % target, classes="private")

    def cmd_HELP(self, src, rest):
        return "Don't panic"

    def render_POST(self, req):
        if not req.user.nick:
            req.setResponseCode(404)
            return "not logged in"

        text = req.args["chatline"][0]
        if text == "/serror":
            req.setResponseCode(500)
            return "serror"

        if text[0] == '/':
            cmdrest = text.split(" ", 1)
            cmd = cmdrest[0].upper()
            rest = ""
            if len(cmdrest) > 1:
                rest = cmdrest[1]

            handler = "cmd_" + cmd[1:]
            if handler in Channel.__dict__:
                r = False
                try:
                    r = Channel.__dict__[handler](self, req.user.nick, rest.strip())
                except:
                    r = sys.exc_info()[1]

                if r:
                    self.lpReply(req.user.nick, r)
            else:
                self.privmsg(req.user.nick, text)
        else:
            self.privmsg(req.user.nick, text)

        return "OK"

    def privmsg(self, src, msg, fromIRC=False, action=False):
        if not fromIRC:
            root.ircd.PRIVMSG("#" + self.name, "[%s]" % src, msg)

        if msg[0:7] == "\001ACTION":
            action = True
            msg = msg[8:-1]

        xmlmsg = str(msg)
        xmlmsg.replace("\n", "<br/>")
        matchobj = regexUrl.search(xmlmsg)
        if matchobj is not None:
            url = matchobj.groups()[0]
            htmlLink = '<a href="%s" target="_blank">%s</a>' % (url, url)
            xmlmsg = xmlmsg[0:matchobj.start()] + htmlLink + xmlmsg[matchobj.end():]

        if action:
            data = divChatline(src="*&nbsp" + src, contents=xmlmsg)
            self.logwrite(data, fromIRC)
        else:
            data = divChatline(src="[%s]" % src, contents=xmlmsg)
            self.logwrite(data, fromIRC)

        return "OK"

class DumpInfo(Resource):
    isLeaf = True

    def render_GET(self, req):
        req.setHeader("Content-Type", "text/plain")
        ret = root.ircd.debug() + "\n"

        for chname, ch in root.channels.items():
            ret += "%s" % ch.debug()
    
        return ret

class LongSession(Session):
    sessionTimeout = 3600 * 2

class tpchat(Resource):
    def __init__(self):
        Resource.__init__(self)
        self.channels = { }
        self.ircd = None

    def getChannel(self, channame, key=None):
        if channame not in self.channels:
            self.channels[channame] = Channel(channame, key=key)

        channel = self.channels[channame]

        if key is not None: # user login/join attempt
            if channel.key is not None:
                if channel.key != key:
                    return None

        return channel

    def getChannelNameFromReq(self, req):
        hostparts = req.getHeader("host").split(".")

        if "channel" in req.args and len(req.args["channel"]) > 0:
            channame = req.args["channel"][0]
        elif len(hostparts) > 2:
            channame = hostparts[-3]
        else:
            channame = ""

        return channame


    def getChild(self, path, req):
        req.user = IUser(req.getSession())

        channame = self.getChannelNameFromReq(req)

#        print req, req.args

        # static file should come before logged-in check
        if path in staticFiles:
            return staticFiles[path]

        if channame:
            LoginPage = lambda msg: FileTemplate("login.html", channel=channame, channelattr='hidden', msg=msg)
        else:
            LoginPage = lambda msg: FileTemplate("login.html", channel="", channelattr="", msg=msg)

        # login must come before logged-in check
        if path == "login":
            if "password" in req.args:
                channel = self.getChannel(channame, key=req.args["password"][0])

                if channel is None:
                    print "incorrect login: %s" % req.args
                    return LoginPage("channel key incorrect")
            else:
                channel = self.getChannel(channame, key="")
           
            if "nick" not in req.args:
                return LoginPage("no nickname given")

            if not isValidNick(req.args["nick"][0]):
                return LoginPage("invalid nickname")

            n = req.args["nick"][0]

            if n in self.ircd.names:
                return LoginPage("nick already exists on irc")

            req.user.nick = n
            req.user.channels.append(channel)
            req.getSession().notifyOnExpire(lambda: self._expired(channame, n))

            print time.ctime(), "*** %s joined %s" % (n, channel)

            return Redirect("/")


        channel = self.getChannel(channame)

        # logged-in check
        if not req.user.nick:
            print "not logged in", req
            return LoginPage("")

        # these must come after logged-in check
        if path == "log":
#            print "get channel data", req, req.args
            return channel

        if path == "logout":
            print "logout", req
            req.getSession().expire()
            return LoginPage("logged-out")

        if not path:
#            print "no path", req
            return FileTemplate("chat.html", nickname=req.user.nick)

        print "else", req
        return Resource.getChild(self, path, req)
   
    def _expired(self, chan, nick):
        print "*** %s idled out of #%s" % (nick, chan)
        self.getChannel(chan).lpDone(nick)

class tpircd(twisted.protocols.basic.LineReceiver):
    def __init__(self):
        self.uids = { }
        self.names = { }
        self.nextuid = 0xAAAAA
        self.sid = tpconfig.ircd_sid

    def debug(self):
        ret = "sid=%s\n" % self.sid

        for k, id in self.names.items():
            ret += "%s %s\n" % (k, id)

        return ret

    def lineReceived(self, line):
        if not line:
            print "empty line received from irc server"
            return

        src = ""

        if line[0] == ":":
            src, _, line = line[1:].partition(" ")

        cmd, _, rest = line.partition(" ")

        handler = "on_" + cmd
        if handler in tpircd.__dict__:
            r = True
            try:
                r = tpircd.__dict__[handler](self, src, rest)
            finally:
                if r or verbose:
                    print "<", line
        else:
            print "UNHANDLED %s :%s %s" % (cmd, src, line)

    def connectionMade(self):
        self.send("PASS %s 02110000 |" % tpconfig.ircd_passwd)
        self.send("SERVER %s 1 %s :%s" % (tpconfig.ircd_servername, self.sid, tpconfig.ircd_serverdesc))
        self.loguid = self.getuid(tpconfig.ircd_nick, 0xFFFFF)

        root.ircd = self

        reactor.listenTCP(tpconfig.tpchat_port, factory)

        if tpconfig.secure:
            sslContext = ssl.DefaultOpenSSLContextFactory(
                                    tpconfig.secure_key,
                                    tpconfig.secure_cacert)
            reactor.listenSSL(tpconfig.secure_port, factory, contextFactory=sslContext)

    def send(self, line):
        if verbose:
            print ">", line
        self.transport.write(line + "\n")

    def PRIVMSG(self, dest, src, msg):
        msg = str(msg)
        for i in xrange(0, len(msg), 450):
            self.send(":%s PRIVMSG %s :%s" % (self.getuid(src), dest, msg[i:i+450]))

    def join(self, cname):
        self.send(":%s NJOIN %s :%s" % (self.sid, '#' + cname, self.loguid))

    def setkey(self, cname, key):
        self.send(":%s MODE %s :+k %s" % (self.sid, '#' + cname, key))

    def getuid(self, name, newuid=None):
        if not name:
            return self.loguid
       
        if name not in self.uids:
            if newuid is None:
                newuid = self.nextuid
                self.nextuid += 1

            uid = "%0s%04X" % (self.sid, newuid)

            self.uids[name] = uid
            self.names[uid] = name

            self.send(":%s UNICK %s %s %s localhost 127.0.0.1 +i :%s" % (
                       self.sid, name, uid, name, name))
        else:
            uid = self.uids[name]

        return uid

    def on_PING(self, src, rest):
        self.send("PONG " + rest)

        return False

    def on_PRIVMSG(self, src, rest):
        target, _, rest = rest.partition(" ")
        if src in self.names:
            src = self.names[src]

        if target[0] == "#":
            channel = root.getChannel(target[1:])
            channel.privmsg(src, rest[1:], fromIRC=True)
        else:
            pass # XXX: deliver to web user

        return False

    def on_MODE(self, src, rest):
        target, modes = rest.split(" ", 3)
        if " " in modes:
            modes, args = modes.split(" ")

        if target in root.channels:
            channel = root.getChannel(target[1:])
            for m in modes:
                if m == "k":
                    channel.key = args.pop(0)
#                    print "%s key='%s'" % (channel, channel.key)
                elif m == "l":
                    limit = args.pop(0)
        return True
            

    def on_UNICK(self, src, rest):
        nick, uid, rest = rest.split(" ", 2)
        self.names[uid] = nick
        self.uids[nick] = uid

        return True

    def on_SQUIT(self, src, rest):
        disconnsid, rest = rest.split(" ", 1)
        if disconnsid == self.sid:
            print "Booted; reconnecting"
            self.transport.loseConnection()
            connect_ircd()

        return True

    def on_NJOIN(self, src, rest):
        cname, rest = rest.split(" ", 1)
        channel = root.getChannel(cname[1:])

#        for uid in src[1:].split(" "):
#            nick = self.names[uid]
#            channel.members[nick] = { }

        return True

class ircdFactory(protocol.ReconnectingClientFactory):
    protocol = tpircd

class FileTemplate(Resource):
    def __init__(self, fn, **kwargs):
        self.contents = file(os.path.join(tpconfig.htdocs_path, fn), "r").read() % kwargs

    def render_GET(self, req):
        return self.contents

staticFiles = { 
    'debug': DumpInfo()
}

def connect_ircd():
    reactor.connectTCP(tpconfig.real_ircd_server, tpconfig.real_ircd_port, ircdFactory())

def main():
    global root, factory

    for fn in "robots.txt favicon.ico style.css tpchat.js tpstyle.css".split():
        staticFiles[fn] = File(os.path.join(tpconfig.htdocs_path, fn))

    root = tpchat()

    factory = Site(root)
    factory.sessionFactory = LongSession

    connect_ircd()

    reactor.run()

if __name__ == "__main__":
    main()

