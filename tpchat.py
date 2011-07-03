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

import tpconfig

import time
import os
import re

divTimestampStart = '<div class="msg timestamp">' # to detect daily divisions
def divTimestamp(fileoffset):
    if fileoffset == 0:
        return divTimestampStart + '<div class="date" timet="%s">%s</div></div>' % (getDateString(), time.strftime("%Y-%b-%d"))
    else:
        ahref = '<a href="javascript:get_backlog(%s)"><div class="date" timet="%s">%s&#x2B06;</div></a>' % (fileoffset, getDateString(), time.strftime("%x"))
        return divTimestampStart + ahref + '</div>'

fmtdivChatline = '''
<div class="msg">
<div class="time" timet="%s">%s</div>
<div class="src"> %s</div>
<div class="contents"> %s</div>
</div>''' 

def divChatline(src, contents):
    t = getClockString()
    return fmtdivChatline % (getClockString(), time.strftime("%H:%M"), src, contents)

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
    def __init__(self, name, key=None):
        self.name = name
        self.logfn = self.name + ".log"
        self.listeners = { }
        self.key = key
        self.members = { }
        self.lastWriteTime = 0
        try:
            self.contents = file(os.path.join(tpconfig.log_path, self.logfn)).read()
        except IOError:
            self.contents = ""

        root.ircd.join(name)
        if key is not None:
            root.ircd.setkey(name, key) 

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
            data += divTimestamp(len(self.contents))

        data += divChatline(src or self.name, xmlmsg)

        self.contents += data

        with file(self.logfn, "a") as fp:
            fp.write(data)

        if not fromIRC:
            root.ircd.sendToChannel(self.name, src, msg)

        smsg = '<span nextt="%s" id="log">%s</span>' % (len(self.contents), data)
        for nick, req in self.listeners.iteritems():
            req.write(smsg)
            req.finish()

        self.listeners = { }

    def render_GET(self, req):
        t = 0

        try:
            t = int(req.args["t"][0])
        except:
            t = -len(self.contents)

        if t < 0:
            t = self.contents[:-t].rfind(divTimestampStart)
        else:
            t = self.contents[t:].find(divTimestampStart)

        if t >= len(self.contents) or t == -1:
            self.listeners[req.user.nick] = req
            return NOT_DONE_YET

        history = self.contents[t:]
        history.replace("\n", "<br/>")
#        msg = '<head><link type="text/css" rel="stylesheet" href="style.css"/></head>'
        msg = '<span t="%s" nextt="%s" id="log">%s</span>' % (t, len(self.contents)+1, history)
        return msg

    def render_POST(self, req):
        if not req.user.nick:
            req.setResponseCode(404)
            return "not logged in"

        self.logwrite("[%s]" % req.user.nick, req.args["chatline"][0])
        return "OK"


class LoginFile(File):
    def __init__(self, msg=""):
        File.__init__(self, "login.html")
   
    def render_POST(self, req):
        return self.render_GET(req)

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
        self.ircd = None

    def getChild(self, path, req):
        hostparts = req.getHeader("host").split(".")

        if len(hostparts) < 3:
            channame = "errors"
        else: 
            channame = hostparts[-3]

        req.user = IUser(req.getSession())

#        print req, req.args

        # static file should come before logged-in check
        if path in staticFiles:
            return staticFiles[path]

        # login must come before logged-in check
        if path == "login":
            if "password" in req.args:
                channel = self.getChannel("#" + channame, key=req.args["password"][0])

                if channel is None:
                    print "incorrect login: %s" % req.args
                    return LoginPage # channel key incorrect
            else:
                channel = self.getChannel("#" + channame, key="")
            
            if "nick" in req.args and isValidNick(req.args["nick"][0]):
                n = req.args["nick"][0]
                if n not in self.ircd.names: # if not already exists on irc
                    req.user.nick = n
                    req.user.channels.append(channel)

                    print time.ctime(), "*** %s joined %s" % (n, channel)

                    return Redirect("/")

            return LoginPage

        channel = self.getChannel("#" + channame)

        # logged-in check
        if not req.user.nick:
            print "not logged in", req
            return LoginPage

        # these must come after logged-in check
        if path == "log":
#            print "get channel data", req, req.args
            return channel

        if path == "logout":
            print "logout", req
            req.getSession().expire()
            return LoginPage

        if not path:
#            print "no path", req
            return FileTemplate("chat.html", { 'nickname': req.user.nick })

        print "else", req
        return Resource.getChild(self, path, req)
    
    def getChannel(self, channame, key=None):
        if channame not in self.channels:
            self.channels[channame] = Channel(channame, key=key)

        channel = self.channels[channame]

        if key is not None: # user login/join attempt
            if channel.key is not None:
                if channel.key != key:
                    return None

        return channel

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
                if r:
                    print "<", line
        else:
            print "UNHANDLED %s :%s %s" % (cmd, src, line)

    def connectionMade(self):
        self.send("PASS %s 02110000 |" % tpconfig.ircd_passwd)
        self.send("SERVER %s 1 %s :%s" % (tpconfig.ircd_servername, self.sid, tpconfig.ircd_serverdesc))
        self.loguid = self.getuid(tpconfig.ircd_nick, 0xFFFFF)

        root.ircd = self

        reactor.listenTCP(tpconfig.tpchat_port, factory)

    def send(self, line):
#        print ">", line
        self.transport.write(line + "\n")

    def sendToChannel(self, chan, src, msg):
        msg = str(msg)
        for i in xrange(0, len(msg), 450):
            self.send(":%s PRIVMSG %s :%s" % (self.getuid(src), chan, msg[i:i+450]))

    def join(self, cname):
        self.send(":%s NJOIN %s :%s" % (self.sid, cname, self.loguid))

    def setkey(self, cname, key):
        self.send(":%s MODE %s :+k %s" % (self.sid, cname, key))

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
        channame, _, rest = rest.partition(" ")
        if src in self.names:
            src = self.names[src]

        channel = root.getChannel(channame)
        if rest[0:8] == ":\001ACTION":
            channel.logwrite("*&nbsp" + src, rest[9:-1], fromIRC=True)
        else:
            channel.logwrite("[%s]" %  src, rest[1:], fromIRC=True)

        return False

    def on_MODE(self, src, rest):
        target, modes = rest.split(" ", 3)
        if " " in modes:
            modes, args = modes.split(" ")

        if target in root.channels:
            channel = root.getChannel(target)
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
            log("Booted; reconnecting")
            self.transport.finish() # XXX
            self.transport.connect() # XXX

        return True

    def on_NJOIN(self, src, rest):
        cname, rest = rest.split(" ", 1)
        channel = root.getChannel(cname)
#        for uid in src[1:].split(" "):
#            nick = self.names[uid]
#            channel.members[nick] = { }

        return True

class ircdFactory(protocol.ReconnectingClientFactory):
    protocol = tpircd

class FileTemplate(Resource):
    def __init__(self, fn, d):
        self.contents = file(os.path.join(tpconfig.htdocs_path, fn), "r").read() % d

    def render_GET(self, req):
        return self.contents

staticFiles = { 
    'debug': DumpInfo()
}

LoginPage = LoginFile()

def main():
    global root, factory

    for fn in "robots.txt favicon.ico style.css tpchat.js".split():
        staticFiles[fn] = File(os.path.join(tpconfig.htdocs_path, fn))

    root = tpchat()

    factory = Site(root)

    reactor.connectTCP(tpconfig.real_ircd_server, tpconfig.real_ircd_port, ircdFactory())

    reactor.run()

if __name__ == "__main__":
    main()
