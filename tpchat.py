#!/usr/bin/python

from twisted.internet import reactor, protocol
from twisted.python import log
from twisted.python.components import registerAdapter
from twisted.web.server import Site, NOT_DONE_YET, Session
from twisted.web.resource import Resource
from twisted.web.static import File
from twisted.web.util import Redirect

import twisted.protocols.basic
from zope.interface import Interface, Attribute, implements

ircd_passwd = "blah"
ircd_servername = "ircweb-dev2.localhost"
ircd_serverdesc = "Textpunks dev server"

def getClockString():
    return "00:00"

class IUser(Interface):
    value = Attribute("user session")

class User(object):
    implements(IUser)
    def __init__(self, session):
        self.nick = ""

registerAdapter(User, Session, IUser)

def isValidNick(s):
    return len(s) > 0

class Channel(Resource):
    isLeaf = True
    def __init__(self, name):
        self.name = name
        self.logfn = self.name + ".log"
        self.listeners = { }
        self.contents = "--- channel %s\n" % name
        self.joinedIRC = False

    def logwrite(self, msg):
        self.contents += msg

        with file(self.logfn, "a") as fp:
            fp.write(msg)

        for nick, req in self.listeners.iteritems():
            req.write(msg)
            req.finish()

        self.listeners = { }

    def render_GET(self, req):
        t = req.args.get("t", 0)
        if t > len(self.contents):
            self.listeners[req.user.nick] = req
            return NOT_DONE_YET

        history = self.contents[t:]

        history.replace("\n", "<br/>")
      
        msg = '<span t="%s" id="log">%s</span>' % (len(self.contents), history)
        print msg
        return msg

    def render_POST(self, req):
        msg = "%s [%s] %s" % (getClockString(), req.user.nick, req.args["chatline"][0])
        self.logwrite(msg)
        return "OK"

LoginPage = File("login.html")
MainPage = File("chat.html")

def getChannel(req):
    return req.getHeader("host").split(".")[-3]

class tpchat(Resource):
#    isLeaf = True
    def __init__(self):
        Resource.__init__(self)
        self.channels = { }

    def getChild(self, path, req):
        channame = getChannel(req)

        if channame not in self.channels:
            self.channels[channame] = Channel(channame)

        channel = self.channels[channame]
        print channame, path, req, channel

        req.user = IUser(req.getSession())

        if path == "login":
            if "nick" in req.args and isValidNick(req.args["nick"][0]):
                n = req.args["nick"][0]

                req.user.nick = n
                return MainPage

            return LoginPage

        if path == "logout":
            req.getSession().expire()
            return LoginPage

        if not req.user.nick:
            return LoginPage

        if path == "log":
            return channel

        if not path:
            return MainPage

        return Resource.getChild(self, path, req)

class tpircd(twisted.protocols.basic.LineReceiver):
    def __init__(self):
        self.uids = { }
        self.names = { }
        self.nextuid = 0xAAAAA
        self.sid = "100B"
        self.contents = { }

    def log(self, cname, data):
        logline = data.strip() + "\n"
        channel = root.getChannel(cname)
        channel.logwrite(logline)

    def lineReceived(self, line):
        if not line:
            print "empty line received from irc server"
            return

        src = ""

        if line[0] == ":":
            src, _, line = line[1:].partition(" ")

        cmd, _, rest = line.partition(" ")

        try:
            r = tpircd.__dict__["on_" + cmd](self, src, rest)
            if r:
                print "<", line
        except KeyError:
            print "??", src, line

    def connectionMade(self):
        self.send("PASS %s 02110000 |" % ircd_passwd)
        self.send("SERVER %s 1 %s :%s" % (ircd_servername, self.sid, ircd_serverdesc))
        self.loguid = self.getuid("_", 0xFFFFF)

    def send(self, line):
        print ">", line
        self.transport.write(line + "\n")

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

        return uid

    def on_PING(self, src, rest):
        self.send("PONG " + rest)

        return False

    def on_PRIVMSG(self, src, rest):
        channel, _, rest = rest.partition(" ")
        if src in self.names:
            src = self.names[src]

        logline = "%s [%s] %s" % (getClockString(), src, rest[1:])

        self.log(channel, logline) # XXX

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

        if not channel.joinedIRC:
            self.send(":%s NJOIN %s :%s" % (self.sid, cname, self.loguid))
            channel.joinedIRC = True

        return True

class ircdFactory(protocol.ReconnectingClientFactory):
    protocol = tpircd

root = tpchat()

root.putChild("robots.txt", File("robots.txt"))
root.putChild("favicon.ico", File("favicon.ico"))

factory = Site(root)
reactor.listenTCP(4444, factory)

# https://<channel>.ideatrial.com -> if not nick, redirect to /login.html
reactor.connectTCP("localhost", 6667, ircdFactory())

reactor.run()
