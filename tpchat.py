#!/usr/bin/python

from twisted.internet import reactor, protocol, defer
from twisted.python import log
from twisted.python.components import registerAdapter
from twisted.web.server import Site, NOT_DONE_YET, Session
from twisted.web.resource import Resource
from twisted.web.static import File
from twisted.web.util import Redirect

import twisted.protocols.basic
from zope.interface import Interface, Attribute, implements

import time
import os
import re

ircd_passwd = "blah"
ircd_servername = "ircweb-dev.emups.com"
ircd_serverdesc = "Textpunks dev server"

divTimestamp = '<div class="msg timestamp">'
fmtdivTimestamp = divTimestamp + '<div class="date">%s</div></div>'

fmtdivChatline = '''
<div class="msg">
<div class="time">%s</div>
<div class="src"> [%s]</div>
<div class="contents"> %s</div>
</div>''' 

regexUrl = re.compile(r"(http://\S+)", re.IGNORECASE | re.LOCALE)

def getClockString():
    t = time.localtime()

    if t.tm_isdst == 0:
        tz = time.timezone
    else:
        tz = time.altzone

    return int(time.time() - tz)

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
    def __init__(self, name):
        self.name = name
        self.logfn = self.name + ".log"
        self.listeners = { }
        self.lastWriteTime = 0
        try:
            self.contents = file(self.logfn).read()
        except IOError:
            self.contents = ""

        root.ircd.join(name)

    def __str__(self):
        return "[channel %s]" % self.name

    def debug(self):
        return "%s: %s listeners, %s bytes of content\n" % (self.name, len(self.listeners), len(self.contents))

    def logwrite(self, src, msg, fromIRC=False):
        xmlmsg = str(msg)
        xmlmsg.replace("\n", "<br/>")
        matchobj = regexUrl.search(xmlmsg)
        if matchobj is not None:
            url = matchobj.groups()[0]
            htmlLink = '<a href="%s" target="_blank">%s</a>' % (url, url)
            xmlmsg = xmlmsg[0:matchobj.start()] + htmlLink + xmlmsg[matchobj.end():]

        data = ""

        lastWriteTime = self.lastWriteTime
        self.lastWriteTime = time.time()

        lastymd = time.gmtime(lastWriteTime)[0:2]
        nowymd = time.gmtime()[0:2]

        if lastymd != nowymd:
            data += fmtdivTimestamp % getDateString()

        data += fmtdivChatline % (getClockString(), src or self.name, xmlmsg)

        self.contents += data

        with file(self.logfn, "a") as fp:
            fp.write(data)

        if not fromIRC:
            root.ircd.sendToChannel(self.name, src, msg)

        for nick, req in self.listeners.iteritems():
            smsg = '<span t="%s" id="log">%s</span>' % (len(self.contents), data)
            req.write(smsg)
            req.finish()

        self.listeners = { }

    def render_GET(self, req):

        if "t" in req.args:
            try:
                t = int(req.args["t"][0])
            except:
                t = -1

        if t < 0:
            t = self.contents.rfind(divTimestamp)
            
        if t >= len(self.contents):
            self.listeners[req.user.nick] = req
            return NOT_DONE_YET

        history = self.contents[t:]
        history.replace("\n", "<br/>")
        msg = '<span t="%s" id="log">%s</span>' % (len(self.contents)+1, history)
        return msg

    def render_POST(self, req):
        if not req.user.nick:
            req.setResponseCode(404)
            return "not logged in"

        self.logwrite(req.user.nick, req.args["chatline"][0])
        return "OK"

class DumpInfo(Resource):
    isLeaf = True

    def render_GET(self, req):
        req.setHeader("Content-Type", "text/plain")
        ret = root.ircd.debug() + "\n"

        for chname, ch in root.channels.items():
            ret += "%s" % ch.debug()
    
        return ret

class tpchat(Resource):
    def __init__(self):
        Resource.__init__(self)
        self.channels = { }
        self.users = { }
        self.ircd = None

    def getChild(self, path, req):
        hostparts = req.getHeader("host").split(".")

        if len(hostparts) < 3:
            channame = "errors"
        else: 
            channame = hostparts[-3]

        channel = self.getChannel("#" + channame)
        
        req.user = IUser(req.getSession())
        print time.ctime(), req, path

        # static file should come before logged-in check
        if path in staticFiles:
            return staticFiles[path]

        # login must come before logged-in check
        if path == "login":
            if "nick" in req.args and isValidNick(req.args["nick"][0]):
                n = req.args["nick"][0]

                req.user.nick = n
                req.user.channels.append(channel)

                print "*** %s joined %s" % (req.user.nick, channel)

                return Redirect("/") # LoggedIn()

            return LoginPage

        # logged-in check
        if not req.user.nick:
            return LoginPage

        # these must come after logged-in check
        if not path:
            return FileTemplate("chat.html", { 'nickname': req.user.nick })

        if path == "log":
            return channel

        if path == "logout":
            req.getSession().expire()
            return LoginPage

        return Resource.getChild(self, path, req)
    
    def getChannel(self, channame):
        if channame not in self.channels:
            self.channels[channame] = Channel(channame)

        return self.channels[channame]

class tpircd(twisted.protocols.basic.LineReceiver):
    def __init__(self):
        self.uids = { }
        self.names = { }
        self.nextuid = 0xAAAAA
        self.sid = "100B"

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
                if r:
                    print "<", line
        else:
            print "UNHANDLED %s :%s %s" % (cmd, src, line)

    def connectionMade(self):
        self.send("PASS %s 02110000 |" % ircd_passwd)
        self.send("SERVER %s 1 %s :%s" % (ircd_servername, self.sid, ircd_serverdesc))
        self.loguid = self.getuid("_", 0xFFFFF)

        root.ircd = self

        reactor.listenTCP(4444, factory)

    def send(self, line):
#        print ">", line
        self.transport.write(line + "\n")

    def sendToChannel(self, chan, src, msg):
        msg = str(msg)
        for i in xrange(0, len(msg), 450):
            self.send(":%s PRIVMSG %s :%s" % (self.getuid(src), chan, msg[i:i+450]))

    def join(self, cname):
        self.send(":%s NJOIN %s :%s" % (self.sid, cname, self.loguid))

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
        channel, _, rest = rest.partition(" ")
        if src in self.names:
            src = self.names[src]

        root.getChannel(channel).logwrite(src, rest[1:], fromIRC=True)

        return False

    def on_UNICK(self, src, rest):
        nick, uid, rest = rest.split(" ", 2)
        self.names[uid] = nick
        self.uids[nick] = uid

        return True

    def on_SQUIT(self, src, rest):
        disconnsid, rest = rest.split(" ", 1)
        if disconnsid == self.sid:
            log("Booted; reconnecting")
            self.transport.finish() # XXX
            self.transport.connect() # XXX

        return True

    def on_NJOIN(self, src, rest):
        cname, rest = rest.split(" ", 1)
        channel = root.getChannel(cname)

        return True

class ircdFactory(protocol.ReconnectingClientFactory):
    protocol = tpircd

class FileTemplate(Resource):
    def __init__(self, fn, d):
        self.contents = file(fn, "r").read() % d

    def render_GET(self, req):
        return self.contents

LoginPage = File("login.html")

staticFiles = {
    'robots.txt': File("robots.txt"),
    'favicon.ico': File("favicon.ico"),
    'style.css': File("style.css"),
    'tpchat.js': File("tpchat.js"),
    'debug': DumpInfo()
}

root = tpchat()

factory = Site(root)

# https://<channel>.ideatrial.com -> if not nick, redirect to /login.html
reactor.connectTCP("localhost", 6667, ircdFactory())

reactor.run()
