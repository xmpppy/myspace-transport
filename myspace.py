#! /usr/bin/env python
# $Id: myspace.py,v 1.1 2008-01-08 04:23:52 norman Exp $
version = 'CVS ' + '$Revision: 1.1 $'.split()[1]
#
# MySpace Transport
# 2007 Copyright (c) Norman Rasmussen
#
# This program is free software licensed with the GNU Public License Version 2.
# For a full copy of the license please go here http://www.gnu.org/licenses/licenses.html#GPL

import base64, ConfigParser, os, platform, random, re, select, sha, shelve, signal, socket, sys, time, traceback, functools
import xmpp.client
from myspace_format import mshtmlformat, msnativeformat
from xmpp.protocol import *
from xmpp.browser import *
from xmpp.jep0106 import *
import config, xmlconfig, mslib
from adhoc import AdHocCommands
from toolbox import *

VERSTR = 'MySpaceIM Transport'
rdsocketlist = {}
wrsocketlist = {}
# key is a tuple of 3 values, (frequency in seconds, function, arguments), value is time of next call
timerlist = {}

NODE_AVATAR='jabber:x:avatar x'
NODE_VCARDUPDATE='vcard-temp:x:update x'
NODE_ADMIN='admin'
NODE_ADMIN_REGISTERED_USERS='registered-users'
NODE_ADMIN_ONLINE_USERS='online-users'
NODE_ROSTER='roster'
NS_NICK='http://jabber.org/protocol/nick'

roomenccodere = re.compile('([^-]?)([A-Z-])')
def RoomEncode(msid):
    return JIDEncode(roomenccodere.sub('\\1-\\2', msid))

roomdeccodere = re.compile('-([a-zA-Z-])')
def RoomDecode(msid):
    def decode(m):
        return m.group(1).upper()
    return roomdeccodere.sub(decode, JIDDecode(msid))

class Transport(object):

    # This class is the main collection of where all the handlers for both the MySpace and Jabber

    #Global structures
    userlist = {}
    discoresults = {}
    online = 1
    restart = 0
    offlinemsg = ''

    def __init__(self,jabber):
        self.jabber = jabber
        self.chatcat = {0:(0,{})}
        self.catlist = {}

    def jabberqueue(self,packet):
        if not wrsocketlist.has_key(self.jabber.Connection._sock):
            wrsocketlist[self.jabber.Connection._sock]=[]
        wrsocketlist[self.jabber.Connection._sock].append(packet)

    def myspacequeue(self,fromjid,packet):
        if packet[0] != '\\':
            raise Exception('Invalid packet data: %s' % repr(packet))
        s = self.userlist[fromjid].sock
        if not wrsocketlist.has_key(s):
            wrsocketlist[s]=[]
        wrsocketlist[s].append(packet)

    def findbadconn(self):
        #print rdsocketlist
        for each in self.userlist:
            if config.dumpProtocol: print each, self.userlist[each].sock.fileno()
            if self.userlist[each].sock.fileno() == -1:
                #print each, self.userlist[each].sock.fileno()
                self.ms_closed(self.userlist[each])
            else:
                try:
                    a,b,c = select.select([self.userlist[each].sock],[self.userlist[each].sock],[self.userlist[each].sock],0)
                except:
                    self.ms_closed(self.userlist[each])
        badlist = []
        for each in wrsocketlist.keys():
            try:
                if each.fileno() == -1:
                    badlist.append(each)
            except:
                    badlist.append(each)
        for each in badlist:
            del wrsocketlist[each]
        return

    def register_handlers(self):
        self.jabber.RegisterHandler('message',self.xmpp_message)
        self.jabber.RegisterHandler('presence',self.xmpp_presence)
        self.jabber.RegisterHandler('iq',self.xmpp_iq_discoinfo_results,typ = 'result', ns=NS_DISCO_INFO)
        self.jabber.RegisterHandler('iq',self.xmpp_iq_version,typ = 'get', ns=NS_VERSION)
        self.jabber.RegisterHandler('iq',self.xmpp_iq_register_get, typ = 'get', ns=NS_REGISTER)
        self.jabber.RegisterHandler('iq',self.xmpp_iq_register_set, typ = 'set', ns=NS_REGISTER)
        self.jabber.RegisterHandler('iq',self.xmpp_iq_avatar, typ = 'get', ns=NS_AVATAR)
        self.jabber.RegisterHandler('iq',self.xmpp_iq_gateway_get, typ = 'get', ns=NS_GATEWAY)
        self.jabber.RegisterHandler('iq',self.xmpp_iq_gateway_set, typ = 'set', ns=NS_GATEWAY)
        self.jabber.RegisterHandler('iq',self.xmpp_iq_vcard, typ = 'get', ns=NS_VCARD)
        #self.jabber.RegisterHandler('iq',self.xmpp_iq_notimplemented)
        #self.jabber.RegisterHandler('iq',self.xmpp_iq_mucadmin_set,typ = 'set', ns=NS_MUC_ADMIN)
        #self.jabber.RegisterHandler('iq',self.xmpp_iq_mucadmin_get,typ = 'get', ns=NS_MUC_ADMIN)
        self.disco = Browser()
        self.disco.PlugIn(self.jabber)
        self.adhoccommands = AdHocCommands(userfile)
        self.adhoccommands.PlugIn(self)
        self.disco.setDiscoHandler(self.xmpp_base_disco,node='',jid=config.jid)
        self.disco.setDiscoHandler(self.xmpp_base_disco,node='',jid=config.confjid)
        self.disco.setDiscoHandler(self.xmpp_base_disco,node='',jid='')

    def register_msmsg_handlers(self, con):
        # override the send method to use our queued version 
        con.send = functools.partial(self.myspacequeue, con.fromjid)
        
        con.handlers['online']= self.ms_online
        con.handlers['offline']= self.ms_offline
        con.handlers['chatonline']= self.ms_chatonline
        con.handlers['chatoffline']= self.ms_chatoffline
        con.handlers['login'] = self.ms_login
        con.handlers['loginfail'] = self.ms_loginfail
        con.handlers['subscribe'] = self.ms_subscribe
        con.handlers['message'] = self.ms_message
        con.handlers['messagefail'] = self.ms_messagefail
        con.handlers['chatmessage'] = self.ms_chatmessage
        con.handlers['notify'] = self.ms_notify
        con.handlers['mailalert'] = self.ms_mailalert
        con.handlers['closed'] = self.ms_closed
        con.handlers['avatar'] = self.ms_avatar
        #chatroom handlers
        con.handlers['reqroom'] = self.ms_chat_login
        con.handlers['roominfo'] = self.ms_chat_roominfo
        con.handlers['chatjoin'] = self.ms_chat_join
        con.handlers['chatleave'] = self.ms_chat_leave
        con.handlers['roommessage'] = self.ms_roommessage
        #con.handlers['roommessagefail'] = self.ms_roommessagefail

    def xmpp_message(self, con, event):
        resource = 'messenger'
        fromjid = event.getFrom()
        if fromjid == None:
            return
        fromstripped = fromjid.getStripped().encode('utf8')
        if event.getTo().getNode() != None:
            if self.userlist.has_key(fromstripped):
                msobj=self.userlist[fromstripped]
                if event.getTo().getDomain() == config.jid:
                    msid = event.getTo().getNode()
                    msidenc = msid.encode('utf-8')
                    if event.getBody() == None:
                        action = mslib.MS_msg_action_stoptyping
                        if event.getTag('composing',namespace=NS_CHATSTATES):
                            action = mslib.MS_msg_action_typing
                        msobj.msmsg_send_action(msidenc,action)
                        return
                    # TODO: add text body and html body via msnativeformat support
                    msg = msnativeformat(event.getBody(), None)
                    resource = 'messenger'
                    # normal non-groupchat or conference cases
                    if resource == 'messenger':
                        if event.getType() == None or event.getType() =='normal':
                            # normal message case
                            #print 'got message'
                            # TODO: add msnativeformat support
                            msobj.msmsg_send_message(msidenc,msg)
                        elif event.getType() == 'chat':
                            # normal chat case
                            #print 'got message'
                            # TODO: add msnativeformat support
                            msobj.msmsg_send_message(msidenc,msg)
                        else:
                            #print 'type error'
                            self.jabberqueue(Error(event,ERR_BAD_REQUEST))
                    elif resource == 'chat':
                        if event.getType() == None or event.getType() =='normal':
                            # normal message case
                            #print 'got message'
                            msobj.msmsg_send_chatmessage(msidenc,msg)
                        elif event.getType() == 'chat':
                            # normal chat case
                            #print 'got message'
                            msobj.msmsg_send_chatmessage(msidenc,msg)
                        else:
                            #print 'type error'
                            self.jabberqueue(Error(event,ERR_BAD_REQUEST))
                    else:
                        #print 'resource error'
                        self.jabberqueue(Error(event,ERR_BAD_REQUEST))
                elif config.enableChatrooms and event.getTo().getDomain() == config.confjid:
                    if event.getBody() == None:
                        return
                    msid = RoomDecode(event.getTo().getNode())
                    # Must add resource matching here, ie only connected resource can send to room.
                    if event.getSubject():
                        self.jabberqueue(Error(event,ERR_NOT_IMPLEMENTED))
                        return
                    if event.getTo().getResource() == None or event.getTo().getResource() == '':
                        #print msobj.roomlist, msobj.roomnames
                        if msobj.roomnames.has_key(msid.lower()):
                            room = msobj.roomnames[msid.lower()].encode('utf-8')
                        else:
                            room = None
                        if config.dumpProtocol: print "groupchat room: ",room
                        if room != None:
                            if event.getBody()[0:3] == '/me':
                                type = 2
                                body = event.getBody()[4:].encode('utf-8')
                            else:
                                type = 1
                                body = event.getBody().encode('utf-8')
                            msobj.msmsg_send_roommsg(room,body,type)
                            to = '%s/%s'%(event.getTo(),msobj.username)
                            self.jabberqueue(Message(to=event.getFrom(), frm= to, typ='groupchat',body=event.getBody()))
                        else:
                            self.jabberqueue(Error(event,ERR_BAD_REQUEST))
                else:
                    self.jabberqueue(Error(event,ERR_BAD_REQUEST))
            else:
                if config.dumpProtocol: print 'no item error'
                self.jabberqueue(Error(event,ERR_REGISTRATION_REQUIRED))
        else:
            self.jabberqueue(Error(event,ERR_BAD_REQUEST))

    def xmpp_presence(self, con, event):
        msobj = None
        yrost = None
        fromjid = event.getFrom()
        fromstripped = fromjid.getStripped().encode('utf8')
        if userfile.has_key(fromstripped):
            if event.getTo().getDomain() == config.jid:
                msid = event.getTo().getNode()
                msidenc = msid.encode('utf-8')
                if event.getType() == 'subscribed':
                    if self.userlist.has_key(fromstripped):
                        msobj=self.userlist[fromstripped]
                        if event.getTo() == config.jid:
                            conf = userfile[fromstripped]
                            conf['subscribed']=True
                            userfile[fromstripped]=conf
                            userfile.sync()
                            #For each new user check if rosterx is adversited then do the rosterx message, else send a truckload of subscribes.
                            #Part 1, parse the features out of the disco result
                            features = []
                            if self.discoresults.has_key(event.getFrom().getStripped().encode('utf8')):
                                discoresult = self.discoresults[event.getFrom().getStripped().encode('utf8')]
                                #for i in discoresult.getQueryPayload():
                                if discoresult.getTag('query').getTag('feature'): features.append(discoresult.getTag('query').getAttr('var'))
                            #Part 2, make the rosterX message
                            if NS_ROSTERX in features:
                                m = Message(to = fromjid, frm = config.jid, subject= 'MySpace Roster Items', body = 'Items from MySpace Roster')
                                p=None
                                p= m.setTag('x',namespace = NS_ROSTERX)
                                yrost = msobj.buddylist
                                if config.dumpProtocol: print yrost
                                for each in yrost.keys():
                                    for msid in yrost[each]:
                                        p.addChild(name='item', attrs={'jid':'%s@%s'%(msid,config.jid),'name':msid, 'action':'add'},payload=[Node('group',payload=each)])
                                self.jabberqueue(m)
                                if config.dumpProtocol: print m
                            else:
                                for each in msobj.buddylist.keys():
                                    for msid in msobj.buddylist[each]:
                                        self.jabberqueue(Presence(frm='%s@%s'%(msid,config.jid),to = fromjid, typ='subscribe', status='MySpace messenger contact'))
                            m = Presence(to = fromjid, frm = config.jid)
                            self.jabberqueue(m)
                            self.ms_send_online(fromstripped)
                            self.register_msmsg_handlers(msobj)
                    else:
                        self.jabberqueue(Error(event,ERR_NOT_ACCEPTABLE))
                elif event.getType() == 'subscribe':
                    if self.userlist.has_key(fromstripped):
                        msobj=self.userlist[fromstripped]
                        if event.getTo() == config.jid:
                            conf = userfile[fromstripped]
                            conf['usubscribed']=True
                            userfile[fromstripped]=conf
                            userfile.sync()
                            m = Presence(to = fromjid, frm = config.jid, typ = 'subscribed')
                            self.jabberqueue(m)
                        elif msobj.roster.has_key(msidenc):
                            m = Presence(to = fromjid, frm = event.getTo(), typ = 'subscribed')
                            self.jabberqueue(m)
                        else:
                            #add new user case.
                            if event.getStatus() != None:
                                if config.dumpProtocol: print event.getStatus().encode('utf-8')
                                status = event.getStatus().encode('utf-8')
                            else:
                                status = ''
                            msobj.msmsg_send_addbuddy(msidenc, status)
                            self.jabberqueue(Presence(frm=event.getTo(), to = event.getFrom(), typ = 'subscribed'))
                    else:
                        self.jabberqueue(Error(event,ERR_NOT_ACCEPTABLE))
                elif event.getType() == 'unsubscribe':
                    # User is not interested in contact's presence anymore
                    if self.userlist.has_key(fromstripped):
                        msobj=self.userlist[fromstripped]
                        print repr(msobj.roster)
                        print repr(msid)
                        if msobj.roster.has_key(msid):
                            if event.getStatus() != None:
                                msg = event.getStatus().encode('utf-8')
                            else:
                                msg = ''
                            msobj.msmsg_send_delbuddy(msidenc, msg)
                            self.jabberqueue(Presence(frm=event.getTo(), to = event.getFrom(), typ = 'unsubscribed'))
                    else:
                        self.jabberqueue(Error(event,ERR_NOT_ACCEPTABLE))
                elif event.getType() == 'unsubscribed':
                    # Do not allow contact to see user's presence
                    # should do something more elegant here
                    pass
                elif event.getType() == None or event.getType() == 'available' or event.getType() == 'invisible':
                    # code to add myspace connection goes here
                    if msid != '':
                        return
                    if self.userlist.has_key(fromstripped):
                        msobj=self.userlist[fromstripped]
                        # update status case and additional resource case
                        # update status case
                        if msobj.xresources.has_key(event.getFrom().getResource()):
                            #update resource record
                            msobj.xresources[event.getFrom().getResource()]=(event.getShow(),event.getPriority(),event.getStatus(),msobj.xresources[event.getFrom().getResource()][3])
                            if config.dumpProtocol: print "Update resource login: %s" % msobj.xresources
                        else:
                            #new resource login
                            msobj.xresources[event.getFrom().getResource()]=(event.getShow(),event.getPriority(),event.getStatus(),time.time())
                            if config.dumpProtocol: print "New resource login: %s" % msobj.xresources
                            #send roster as is
                            self.ms_send_online(fromstripped,event.getFrom().getResource())
                        #print fromstripped, event.getShow().encode('utf-8'), event.getStatus().encode('utf-8')
                        self.xmpp_presence_do_update(event,fromstripped)
                    else:
                        # open connection case
                        try:
                            conf = userfile[fromstripped]
                        except:
                            self.jabberqueue(Message(to=fromstripped,subject='Transport Configuration Error',body='The transport has found that your configuration could not be loaded. Please re-register with the transport'))
                            del userfile[fromstripped]
                            userfile.sync()
                            return
                        msobj = mslib.MySpaceCon(conf['username'].encode('utf-8'),conf['password'].encode('utf-8'), fromstripped,config.host,config.dumpProtocol)
                        s = msobj.connect()
                        if s != None:
                            rdsocketlist[s]=msobj
                            self.userlist[fromstripped]=msobj
                            self.register_msmsg_handlers(msobj)
                            msobj.event = event
                            if event.getShow() == 'xa' or event.getShow() == 'away':
                                msobj.away = 'away'
                            elif event.getShow() == 'dnd':
                                msobj.away = 'dnd'
                            elif event.getShow() == 'invisible':
                                msobj.away = 'invisible'
                            else:
                                msobj.away = None
                            msobj.showstatus = event.getStatus()
                            #Add line into currently matched resources
                            msobj.xresources[event.getFrom().getResource()]=(event.getShow(),event.getPriority(),event.getStatus(),time.time())
                        else:
                            self.jabberqueue(Error(event,ERR_REMOTE_SERVER_TIMEOUT))
                elif event.getType() == 'unavailable':
                    # Match resources and remove the newly unavailable one
                    if self.userlist.has_key(fromstripped):
                        msobj=self.userlist[fromstripped]
                        #print 'Resource: ', event.getFrom().getResource(), "To Node: ",msid
                        if msid =='':
                            self.ms_send_offline(fromstripped,event.getFrom().getResource())
                            if msobj.xresources.has_key(event.getFrom().getResource()):
                                del msobj.xresources[event.getFrom().getResource()]
                                self.xmpp_presence_do_update(event,fromstripped)
                            #Single resource case
                            #print msobj.xresources
                            if msobj.xresources == {}:
                                if config.dumpProtocol: print 'No more resource logins'
                                if timerlist.has_key(msobj.alertpollobj):
                                    del timerlist[msobj.alertpollobj]
                                del self.userlist[msobj.fromjid]
                                if rdsocketlist.has_key(msobj.sock):
                                    del rdsocketlist[msobj.sock]
                                if wrsocketlist.has_key(msobj.sock):
                                    del wrsocketlist[msobj.sock]
                                msobj.sock.close()
                                del msobj
                    else:
                        self.jabberqueue(Presence(to=fromjid,frm = config.jid, typ='unavailable'))
            elif config.enableChatrooms and event.getTo().getDomain() == config.confjid:
                msid = RoomDecode(event.getTo().getNode())
                msidenc = msid.encode('utf-8')
                if self.userlist.has_key(fromstripped):
                    msobj=self.userlist[fromstripped]
                    if None: # TODO: Add MySpace room code, yahoo was: msobj.connok:
                        if config.dumpProtocol: print "chat presence"
                        msobj.roomnames[msid.lower()] = msid
                        if event.getType() == 'available' or event.getType() == None or event.getType() == '':
                            nick = event.getTo().getResource()
                            msobj.nick = nick
                            if not msobj.chatlogin:
                                msobj.msmsg_send_conflogon()
                                msobj.msmsg_send_chatlogin(None)
                                msobj.chatresource = event.getFrom().getResource()
                                msobj.roomtojoin = msidenc
                            else:
                                msobj.msmsg_send_chatjoin(msidenc)
                        elif event.getType() == 'unavailable':
                            # Must add code to compare from resources here
                            msobj.msmsg_send_chatleave(msidenc)
                            msobj.msmsg_send_chatlogout()
                            msobj.msmsg_send_conflogoff()
                        else:
                            self.jabberqueue(Error(event,ERR_FEATURE_NOT_IMPLEMENTED))
                    else:
                        self.jabberqueue(Error(event,ERR_BAD_REQUEST))
                else:
                    self.jabberqueue(Error(event,ERR_BAD_REQUEST))
            else:
                self.jabberqueue(Error(event,ERR_BAD_REQUEST))
        else:
            # Need to add auto-unsubscribe on probe events here.
            if event.getType() == 'probe':
                self.jabberqueue(Presence(to=event.getFrom(), frm=event.getTo(), typ='unsubscribe'))
                self.jabberqueue(Presence(to=event.getFrom(), frm=event.getTo(), typ='unsubscribed'))
            elif event.getType() == 'unsubscribed':
                pass
            elif event.getType() == 'unsubscribe':
                self.jabberqueue(Presence(frm=event.getTo(),to=event.getFrom(),typ='unsubscribed'))
            else:
                self.jabberqueue(Error(event,ERR_REGISTRATION_REQUIRED))

    def xmpp_presence_do_update(self,event,fromstripped):
        age =None
        priority = None
        resource = None
        msobj=self.userlist[fromstripped]
        for each in msobj.xresources.keys():
            #print each,msobj.xresources
            if msobj.xresources[each][1]>priority:
                #if priority is higher then take the highest
                age = msobj.xresources[each][3]
                priority = msobj.xresources[each][1]
                resource = each
            elif msobj.xresources[each][1]==priority:
                #if priority is the same then take the oldest
                if msobj.xresources[each][3]<age:
                    age = msobj.xresources[each][3]
                    priority = msobj.xresources[each][1]
                    resource = each
        if resource == event.getFrom().getResource():
            #only update shown status if resource is current datasource
            if event.getShow() == None:
                if event.getStatus() != None:
                    msobj.msmsg_send_status(None,event.getStatus())
                else:
                    msobj.msmsg_send_status()
                msobj.away = None
            elif event.getShow() == 'xa' or event.getShow() == 'away':
                msobj.msmsg_send_status('away',event.getStatus())
                msobj.away = 'away'
            elif event.getShow() == 'dnd':
                msobj.msmsg_send_status('dnd',event.getStatus())
                msobj.away= 'dnd'
            elif event.getType() == 'invisible':
                msobj.msmsg_send_status('invisible',None)
                msobj.away= 'invisible'

    def xmpp_iq_notimplemented(self, con, event):
        self.jabberqueue(Error(event,ERR_FEATURE_NOT_IMPLEMENTED))


    # New Disco Handlers
    def xmpp_base_disco(self, con, event, type):
        fromjid = event.getFrom().getStripped().__str__()
        fromstripped = event.getFrom().getStripped().encode('utf8')
        to = event.getTo()
        node = event.getQuerynode();
        if to == config.jid:
            if node == None:
                if type == 'info':
                    features = [NS_VERSION,NS_COMMANDS,NS_AVATAR,NS_CHATSTATES]
                    if config.allowRegister or userfile.has_key(fromjid):
                        features = [NS_REGISTER] + features
                    return {
                        'ids':[
                            {'category':'gateway','type':'myspace','name':VERSTR}],
                        'features':features}
                if type == 'items':
                    list = [
                        {'node':NODE_ROSTER,'name':config.discoName + ' Roster','jid':config.jid}]
                    if config.enableChatrooms:
                        list.append({'jid':config.confjid,'name':config.discoName + ' Chatrooms'})
                    if fromjid in config.admins:
                        list.append({'node':NODE_ADMIN,'name':config.discoName + ' Admin','jid':config.jid})
                    return list
            elif node == NODE_ADMIN:
                if type == 'info':
                    return {'ids':[],'features':[]}
                if type == 'items':
                    if not fromjid in config.admins:
                        return []
                    return [
                        {'node':NS_COMMANDS,'name':config.discoName + ' Commands','jid':config.jid},
                        {'node':NODE_ADMIN_REGISTERED_USERS,'name':config.discoName + ' Registered Users','jid':config.jid},
                        {'node':NODE_ADMIN_ONLINE_USERS,'name':config.discoName + ' Online Users','jid':config.jid}]
            elif node == NODE_ROSTER:
                if type == 'info':
                    return {'ids':[],'features':[]}
                if type == 'items':
                    list = []
                    if self.userlist.has_key(fromstripped):
                        for msid in self.userlist[fromstripped].roster.keys():
                            list.append({'jid':'%s@%s' %(msid,config.jid),'name':msid})
                    return list
            elif node.startswith(NODE_ADMIN_REGISTERED_USERS):
                if type == 'info':
                    return {'ids':[],'features':[]}
                if type == 'items':
                    if not fromjid in config.admins:
                        return []
                    nodeinfo = node.split('/')
                    list = []
                    if len(nodeinfo) == 1:
                        for each in userfile.keys():
                            #list.append({'node':'/'.join([NODE_ADMIN_REGISTERED_USERS, each]),'name':each,'jid':config.jid})
                            list.append({'name':each,'jid':each})
                    #elif len(nodeinfo) == 2:
                        #fromjid = nodeinfo[1]
                        #list = [
                            #{'name':fromjid + ' JID','jid':fromjid}]
                    return list
            elif node.startswith(NODE_ADMIN_ONLINE_USERS):
                if type == 'info':
                    return {'ids':[],'features':[]}
                if type == 'items':
                    if not fromjid in config.admins:
                        return []
                    nodeinfo = node.split('/')
                    list = []
                    if len(nodeinfo) == 1:
                        for each in self.userlist.keys():
                            #list.append({'node':'/'.join([NODE_ADMIN_ONLINE_USERS, each]),'name':each,'jid':config.jid})
                            list.append({'name':each,'jid':each})
                    #elif len(nodeinfo) == 2:
                        #fromjid = nodeinfo[1]
                        #list = [
                            #{'name':fromjid + ' JID','jid':fromjid}]
                    return list
            else:
                self.jabber.send(Error(event,ERR_ITEM_NOT_FOUND))
                raise NodeProcessed
        elif to.getDomain() == config.jid:
            if self.userlist.has_key(fromstripped):
                msid = event.getTo().getNode()
                if type == 'info':
                    if self.userlist[fromstripped].roster.has_key(msid):
                        features = [NS_VCARD,NS_VERSION,NS_CHATSTATES]
                        if userfile[fromstripped.encode('utf-8')].has_key('avatar'):
                            if userfile[fromstripped.encode('utf-8')]['avatar'].has_key(msid):
                                features.append(NS_AVATAR)
                        return {
                            'ids':[
                                {'category':'client','type':'myspace','name':msid}],
                            'features':features}
                    else:
                        self.jabberqueue(Error(event,ERR_NOT_ACCEPTABLE))
                if type == 'items':
                    if self.userlist[fromstripped].roster.has_key(msid):
                        return []
            else:
                self.jabberqueue(Error(event,ERR_NOT_ACCEPTABLE))
        elif config.enableChatrooms and to == config.confjid:
            if node == None:
                if type == 'info':
                    #if we return disco info for our subnodes when the server asks, then we get added to the server's item list
                    if fromstripped == config.mainServerJID:
                        raise NodeProcessed
                    return {
                        'ids':[
                            {'category':'conference','type':'myspace','name':VERSTR + ' Chatrooms'}],
                        'features':[NS_MUC,NS_VERSION]}
                if type == 'items':
                    if self.chatcat[0][0] < (time.time() - (5*60)):
                        t = None # TODO: Add MySpace room code, yahoo was: roomlist.getcata(0)
                        if t != None:
                            for each in t.keys():
                                self.chatcat[each] = (time.time(),t[each])
                    list = []
                    for each in self.chatcat[0][1]:
                        list.append({'jid':to,'node':each,'name':self.chatcat[0][1][each]})
                    return list
            else:
                if type == 'info':
                    if self.chatcat[0][1].has_key(node):
                        return {
                            'ids':[
                                {'name':self.chatcat[0][1][node]}],
                            'features':[]}
                if type == 'items':
                    # Do get room item
                    if not self.catlist.has_key(node):
                        t = None # TODO: Add MySpace room code, yahoo was: roomlist.getrooms(node)
                        if t != None:
                            self.catlist[node] = (time.time(),t)
                    else:
                        if self.catlist[node][0] < (time.time() - 5*60):
                            t = None # TODO: Add MySpace room code, yahoo was: roomlist.getrooms(node)
                            if t != None:
                                self.catlist[node] = (time.time(),t)
                    # Do get more categories
                    if not self.chatcat.has_key(node):
                        t = None # TODO: Add MySpace room code, yahoo was: roomlist.getcata(node)
                        if t != None:
                            self.chatcat[node] = (time.time(),t)
                    else:
                        if self.chatcat[node][0] < (time.time() - 5*60):
                            t = None # TODO: Add MySpace room code, yahoo was: roomlist.getcata(node)
                            if t != None:
                                self.chatcat[node] = (time.time(),t)
                    list = []
                    if len(node.split('/')) == 1:
                        #add catagories first
                        if self.chatcat.has_key(node):
                            for each in self.chatcat[node][1].keys():
                                if each != 0 and 0 in self.chatcat[node][1].keys():
                                    list.append({'jid':to,'node':each,'name':self.chatcat[node][1][0][each]})
                        # First level of nodes
                        for z in self.catlist[node][1].keys():
                            each = self.catlist[node][1][z]
                            if each.has_key('type'):
                                if each['type'] == 'myspace':
                                    if each.has_key('rooms'):
                                        for c in each['rooms'].keys():
                                            n = RoomEncode('%s:%s' % (each['name'],c))
                                            list.append({'jid':'%s@%s'%(n,config.confjid),'name':'%s:%s'%(each['name'],c)})
                    return list
        elif config.enableChatrooms and to.getDomain() == config.confjid:
            if type == 'info':
                msid = RoomDecode(event.getTo().getNode())
                lobby,room = msid.split(':')
                result = {
                    'ids':[
                        {'category':'conference','type':'myspace','name':msid}],
                    'features':[NS_MUC]}
                for node in self.catlist.keys():
                    if self.catlist[node][1].has_key(lobby):
                        t = self.catlist[node][1][lobby]
                        if t['rooms'].has_key(room):
                            data = {'muc#roominfo_description':t['name'],'muc#roominfo_subject':t['topic'],'muc#roominfo_occupants':t['rooms'][room]['users']}
                            info = DataForm(typ = 'result', data= data)
                            field = info.setField('FORM_TYPE')
                            field.setType('hidden')
                            field.setValue('http://jabber.org/protocol/muc#roominfo')
                            result['xdata'] = info
                return result
            if type == 'items':
                return []

    def xmpp_iq_discoinfo_results(self, con, event):
        self.discoresults[event.getFrom().getStripped().encode('utf8')]=event
        raise NodeProcessed

    def xmpp_iq_register_get(self, con, event):
        if event.getTo() == config.jid:
            username = []
            password = []
            fromjid = event.getFrom().getStripped().encode('utf8')
            queryPayload = [Node('instructions', payload = 'Please provide your MySpace username and password')]
            if userfile.has_key(fromjid):
                try:
                    username = userfile[fromjid]['username']
                    password = userfile[fromjid]['password']
                except:
                    pass
                queryPayload += [
                    Node('username',payload=username),
                    Node('password',payload=password),
                    Node('registered')]
            else:
                if not config.allowRegister:
                    return
                queryPayload += [
                    Node('username'),
                    Node('password')]
            m = event.buildReply('result')
            m.setQueryNS(NS_REGISTER)
            m.setQueryPayload(queryPayload)
            self.jabberqueue(m)
            #Add disco#info check to client requesting for rosterx support
            i= Iq(to=event.getFrom(), frm=config.jid, typ='get',queryNS=NS_DISCO_INFO)
            self.jabberqueue(i)
        else:
            self.jabberqueue(Error(event,ERR_BAD_REQUEST))
        raise NodeProcessed

    def xmpp_iq_register_set(self, con, event):
        if event.getTo() == config.jid:
            remove = False
            username = False
            password = False
            fromjid = event.getFrom().getStripped().encode('utf8')
            #for each in event.getQueryPayload():
            #    if each.getName() == 'username':
            #        username = each.getData()
            #        print "Have username ", username
            #    elif each.getName() == 'password':
            #        password = each.getData()
            #        print "Have password ", password
            #    elif each.getName() == 'remove':
            #        remove = True
            query = event.getTag('query')
            if query.getTag('username'):
                username = query.getTagData('username')
            if query.getTag('password'):
                password = query.getTagData('password')
            if query.getTag('remove'):
               remove = True
            if not remove and username and password:
                if userfile.has_key(fromjid):
                    conf = userfile[fromjid]
                else:
                    if not config.allowRegister:
                        return
                    conf = {}
                conf['username']=username
                conf['password']=password
                userfile[fromjid]=conf
                userfile.sync()
                m=event.buildReply('result')
                self.jabberqueue(m)
                if self.userlist.has_key(fromjid):
                    self.ms_closed(self.userlist[fromjid])
                if not self.userlist.has_key(fromjid):
                    msobj = mslib.MySpaceCon(username.encode('utf-8'),password.encode('utf-8'), fromjid,config.host,config.dumpProtocol)
                    self.userlist[fromjid]=msobj
                    if config.dumpProtocol: print "try connect"
                    s = msobj.connect()
                    if s != None:
                        if config.dumpProtocol: print "conect made"
                        rdsocketlist[s]=msobj
                    msobj.handlers['login']=self.ms_reg_login
                    msobj.handlers['loginfail']=self.ms_loginfail
                    msobj.handlers['closed']=self.ms_loginfail
                    msobj.event = event
                    msobj.showstatus = None
                    msobj.away = None
            elif remove and not username and not password:
                if self.userlist.has_key(fromjid):
                    self.ms_closed(self.userlist[fromjid])
                if userfile.has_key(fromjid):
                    del userfile[fromjid]
                    userfile.sync()
                    m = event.buildReply('result')
                    self.jabberqueue(m)
                    m = Presence(to = event.getFrom(), frm = config.jid, typ = 'unsubscribe')
                    self.jabberqueue(m)
                    m = Presence(to = event.getFrom(), frm = config.jid, typ = 'unsubscribed')
                    self.jabberqueue(m)
                else:
                    self.jabberqueue(Error(event,ERR_BAD_REQUEST))
            else:
                self.jabberqueue(Error(event,ERR_BAD_REQUEST))
        else:
            self.jabberqueue(Error(event,ERR_BAD_REQUEST))
        raise NodeProcessed

    def xmpp_iq_avatar(self, con, event):
        fromjid = event.getFrom()
        fromstripped = fromjid.getStripped().encode('utf-8')
        if userfile.has_key(fromstripped):
            if event.getTo().getDomain() == config.jid:
                msid = event.getTo().getNode()
            elif config.enableChatrooms and event.getTo().getDomain() == config.confjid:
                msid = event.getTo().getResource()
            else:
                self.jabberqueue(Error(event,ERR_ITEM_NOT_FOUND))
                raise NodeProcessed
            if userfile[fromstripped].has_key('avatar'):
                if userfile[fromstripped]['avatar'].has_key(msid):
                    m = Iq(to = event.getFrom(), frm=event.getTo(), typ = 'result', queryNS=NS_AVATAR, payload=[Node('data',attrs={'mimetype':'image/png'},payload=base64.encodestring(userfile[fromstripped]['avatar'][msid][1]))])
                    m.setID(event.getID())
                    self.jabberqueue(m)
                else:
                    self.jabberqueue(Error(event,ERR_ITEM_NOT_FOUND))
            else:
                self.jabberqueue(Error(event,ERR_ITEM_NOT_FOUND))
        else:
            self.jabberqueue(Error(event,ERR_ITEM_NOT_FOUND))
        raise NodeProcessed

    def xmpp_iq_gateway_get(self, con, event):
        if event.getTo() == config.jid:
            m = Iq(to = event.getFrom(), frm=event.getTo(), typ = 'result', queryNS=NS_GATEWAY, payload=[
                Node('desc',payload='Please enter the MySpace ID of the person you would like to contact.'),
                Node('prompt',payload='MySpace ID')])
            m.setID(event.getID())
            self.jabberqueue(m)
            raise NodeProcessed

    def xmpp_iq_gateway_set(self, con, event):
        fromstripped = event.getFrom().getStripped().encode('utf8')
        if event.getTo() == config.jid and self.userlist.has_key(fromstripped):
            def complete(msid):
                if msid:
                    m = Iq(to = event.getFrom(), frm=event.getTo(), typ = 'result', queryNS=NS_GATEWAY, payload=[
                        Node('jid',payload='%s@%s'%(msid,config.jid)),     # JEP-0100 says use jid,
                        Node('prompt',payload='%s@%s'%(msid,config.jid))]) # but Psi uses prompt
                    m.setID(event.getID())
                else:
                    m = Error(event,ERR_ITEM_NOT_FOUND)
                self.jabberqueue(m)
            query = event.getTag('query')
            userinfo = query.getTagData('prompt')
            msobj = self.userlist[fromstripped]
            msobj.msmsg_send_lookup_user(userinfo,complete)
            raise NodeProcessed

    def xmpp_iq_vcard(self, con, event):
        fromjid = event.getFrom()
        fromstripped = fromjid.getStripped().encode('utf-8')
        if userfile.has_key(fromstripped):
            if event.getTo().getDomain() == config.jid:
                msid = event.getTo().getNode()
            elif config.enableChatrooms and event.getTo().getDomain() == config.confjid:
                msid = event.getTo().getResource()
            else:
                self.jabberqueue(Error(event,ERR_ITEM_NOT_FOUND))
                raise NodeProcessed
            if not self.userlist[fromstripped].contactdetails.has_key(msid):
                self.jabberqueue(Error(event,ERR_ITEM_NOT_FOUND))
                raise NodeProcessed
            m = Iq(to = event.getFrom(), frm=event.getTo(), typ = 'result')
            m.setID(event.getID())
            v = m.addChild(name='vCard', namespace=NS_VCARD)
            v.setTagData(tag='NICKNAME', val=self.userlist[fromstripped].contactdetails[msid]['DisplayName'])
            v.setTagData(tag='FN', val=self.userlist[fromstripped].contactdetails[msid]['UserName'])
            if userfile[fromstripped].has_key('avatar') and \
                userfile[fromstripped]['avatar'].has_key(msid):
                p = v.addChild(name='PHOTO')
                p.setTagData(tag='TYPE', val='image/png')
                p.setTagData(tag='BINVAL', val=base64.encodestring(userfile[fromstripped]['avatar'][msid][1]))
            self.jabberqueue(m)
        else:
            self.jabberqueue(Error(event,ERR_ITEM_NOT_FOUND))
        raise NodeProcessed

    def ms_avatar(self,msobj,msid,avatar):
        hex = None
        conf = userfile[msobj.fromjid]
        if not conf.has_key('avatar'):
            conf['avatar']={}
        if avatar != None:
            a = sha.new(avatar)
            hex = a.hexdigest()
            conf['avatar'][msid]=(hex,avatar)
        elif conf['avatar'].has_key(msid):
            hex = ''
            del conf['avatar'][msid]
        userfile[msobj.fromjid] = conf
        userfile.sync()
        if hex != None:
            if config.dumpProtocol: print "avatar:",hex
            self.ms_online(msobj,msid,forceavatar=1)

    def ms_closed(self, msobj):
        if self.userlist.has_key(msobj.fromjid):
            if not msobj.connok:
                if config.dumpProtocol: print "got closed, on not connok"
                if msobj.moreservers():
                    if rdsocketlist.has_key(msobj.sock):
                        del rdsocketlist[msobj.sock]
                    if wrsocketlist.has_key(msobj.sock):
                        del wrsocketlist[msobj.sock]
                    msobj.sock.close()
                    s= msobj.connect()
                    if s != None:
                        rdsocketlist[s]=msobj
                        self.userlist[msobj.fromjid]=msobj
                        return # this method terminates here - all change please
                else:
                    self.ms_loginfail(msobj)
            self.ms_send_offline(msobj.fromjid)
            self.jabberqueue(Error(Presence(frm = msobj.fromjid, to = config.jid),ERR_REMOTE_SERVER_TIMEOUT))
            if timerlist.has_key(msobj.alertpollobj):
                del timerlist[msobj.alertpollobj]
            if self.userlist.has_key(msobj.fromjid):
                del self.userlist[msobj.fromjid]
            if rdsocketlist.has_key(msobj.sock):
                del rdsocketlist[msobj.sock]
            if wrsocketlist.has_key(msobj.sock):
                del wrsocketlist[msobj.sock]
            if msobj.sock:
                msobj.sock.close()
            del msobj

    def ms_login(self,msobj):
        if config.dumpProtocol: print "got login"
        freq = int(msobj.serverinfo['AlertPollInterval'])
        nextrun = int(time.time()) + random.randrange(freq)
        msobj.alertpollobj=(freq,msobj.msmsg_send_check_mail,())
        timerlist[msobj.alertpollobj] = nextrun
        for each in msobj.xresources.keys():
            mjid = JID(msobj.fromjid)
            mjid.setResource(each)
            self.jabberqueue(Presence(to = mjid, frm = config.jid))
        msobj.handlers['loginfail']= self.ms_loginfail
        msobj.handlers['login']= self.ms_closed
        msobj.connok = True
        msobj.msmsg_send_status(msobj.away, msobj.showstatus)

    def ms_loginfail(self,msobj, reason = None):
        if config.dumpProtocol: print "got login fail: ",reason
        if config.dumpProtocol: print msobj.conncount, msobj.moreservers()
        if msobj.moreservers() and reason == None:
            if rdsocketlist.has_key(msobj.sock):
                del rdsocketlist[msobj.sock]
            if wrsocketlist.has_key(msobj.sock):
                del wrsocketlist[msobj.sock]
            msobj.sock.close()
            s = msobj.connect()
            if s != None:
                rdsocketlist[s]=msobj
                self.userlist[msobj.fromjid]=msobj
                return # this method terminates here - all change please
        else:
            # This is the no more servers or definite error case.
            if reason == 'badpassword' or reason == 'badusername':
                self.jabberqueue(Message(to=msobj.event.getFrom(),frm=config.jid,subject='Login Failure',body='Login Failed to MySpace service. The MySpace Service returned a bad username or password error. Please use the registration function to check your password is correct.'))
            elif reason == 'disconnected':
                self.jabberqueue(Message(to=msobj.event.getFrom(),frm=config.jid,subject='Login Failure',body='Login Failed to MySpace service. This profile has been disconnected by another login.'))
            elif reason == 'locked':
                self.jabberqueue(Message(to=msobj.event.getFrom(),frm=config.jid,subject='Login Failure',body='Login Failed to MySpace service. Your account has been locked by MySpace.'))
            elif reason == 'imageverify':
                self.jabberqueue(Message(to=msobj.event.getFrom(),frm=config.jid,subject='Login Failure',body='Login Failed to MySpace service. Your account needs to be verified, unfortuantely this can not be done using the transport at this time.'))
            else:
                self.jabberqueue(Message(to=msobj.event.getFrom(),frm=config.jid,subject='Login Failure',body='Login Failed to MySpace service. Please check registration details by re-registering in your client'))
            self.jabberqueue(Error(msobj.event,ERR_NOT_AUTHORIZED))
            del self.userlist[msobj.fromjid]
            if rdsocketlist.has_key(msobj.sock):
                del rdsocketlist[msobj.sock]
            if wrsocketlist.has_key(msobj.sock):
                del wrsocketlist[msobj.sock]
            msobj.sock.close()
            del msobj

    def ms_online(self,msobj,msid,forceavatar=0):
        hex = None
        if userfile[msobj.fromjid].has_key('avatar'):
            if config.dumpProtocol: print userfile[msobj.fromjid]['avatar'].keys(), msid
            if userfile[msobj.fromjid]['avatar'].has_key(msid):
                hex = userfile[msobj.fromjid]['avatar'][msid][0]
        if hex == None and forceavatar:
            hex = ''
        #print msobj.xresources.keys()
        for each in msobj.xresources.keys():
            mjid = JID(msobj.fromjid)
            mjid.setResource(each)
            #print mjid, each
            if msobj.roster[msid][2] != None:
                text,xhtml = mshtmlformat(msobj.roster[msid][2])
                status = text
            else:
                status = None
            if config.dumpProtocol: print repr(status)
            b = Presence(to = mjid, frm = '%s@%s/messenger'%(msid, config.jid),priority = 10, show=msobj.roster[msid][1], status=status)
            if msobj.contactdetails.has_key(msid):
                b.addChild('nick', namespace=NS_NICK, payload=msobj.contactdetails[msid]['DisplayName'])
            if hex != None:
                b.addChild(node=Node(NODE_AVATAR,payload=[Node('hash',payload=hex)]))
                b.addChild(node=Node(NODE_VCARDUPDATE,payload=[Node('photo',payload=hex)]))
            self.jabberqueue(b)

    def ms_chatonline(self,msobj, msid):
        #This is service online not person online
        for each in msobj.xresources.keys():
            mjid = JID(msobj.fromjid)
            mjid.setResource(each)
            b = Presence(to = mjid, frm = '%s@%s/chat' %(msid,config.jid), priority = 5)
            self.jabberqueue(b)

    def ms_offline(self,msobj,msid):
        for each in msobj.xresources.keys():
            mjid = JID(msobj.fromjid)
            mjid.setResource(each)
            self.jabberqueue(Presence(to=mjid, frm = '%s@%s/messenger'%(msid, config.jid),typ='unavailable'))

    def ms_chatoffline(self,msobj,msid):
        #This is service offline not person offline
        for each in msobj.xresources.keys():
            mjid = JID(msobj.fromjid)
            mjid.setResource(each)
            self.jabberqueue(Presence(to =mjid, frm = '%s@%s/chat'%(msid, config.jid),typ='unavailable'))

    def ms_subscribe(self,msobj,msid,msg):
        text,xhtml = mshtmlformat(msg)
        self.jabberqueue(Presence(typ='subscribe',frm = '%s@%s' % (msid, config.jid), to=msobj.fromjid,payload=text))

    def ms_message(self,msobj,msid,msg):
        text,xhtml = mshtmlformat(msg)
        m = Message(typ='chat',frm = '%s@%s/messenger' %(msid,config.jid), to=msobj.fromjid,body=text,payload = [xhtml])
        m.setTag('active',namespace=NS_CHATSTATES)
        self.jabberqueue(m)

    def ms_messagefail(self,msobj,msid,msg):
        text,html = mshtmlformat(msg)
        self.jabberqueue(Error(Message(typ='chat',to = '%s@%s' %(msid,config.jid), frm=msobj.fromjid,body=text),ERR_SERVICE_UNAVAILABLE))

    def ms_chatmessage(self,msobj,msid,msg):
        text,xhtml = mshtmlformat(msg)
        m = Message(typ='chat',frm = '%s@%s/chat' %(msid,config.jid), to=msobj.fromjid,body=text)
        m.setTag('active',namespace=NS_CHATSTATES)
        self.jabberqueue(m)

    def ms_roommessage(self,msobj,msid,room,msg):
        text,xhtml = mshtmlformat(msg)
        to = JID(msobj.fromjid)
        to.setResource(msobj.chatresource)
        if msobj.roomlist[room]['byyid'].has_key(msid):
            nick = msobj.roomlist[room]['byyid'][msid]['nick']
        else:
            nick = msid
        self.jabberqueue(Message(typ = 'groupchat', frm = '%s@%s/%s' % (RoomEncode(room),config.confjid,nick),to=to,body=text))

    def ms_notify(self,msobj,msid,state):
        m = Message(typ='chat',frm = '%s@%s/messenger' %(msid,config.jid), to=msobj.fromjid)
        if state:
            m.setTag('composing',namespace=NS_CHATSTATES)
        else:
            m.setTag('paused',namespace=NS_CHATSTATES)
        self.jabberqueue(m)

    def ms_mailalert(self,msobj,notifications):
        for notification in notifications:
            m = Message(frm=config.jid,to=msobj.fromjid,typ='headline', subject = 'New ' + notification[0], body = 'You have new ' + notification[0] + '.')
            p = m.setTag('x', namespace = 'jabber:x:oob')
            p.addChild(name = 'url',payload=notification[1])
            self.jabberqueue(m)

    def ms_reg_login(self,msobj):
        # registration login handler
        if config.dumpProtocol: print "got reg login"
        #m = msobj.event.buildReply('result')
        #self.jabberqueue(m)
        self.jabberqueue(Presence(to=msobj.event.getFrom(),frm=msobj.event.getTo(),typ=msobj.event.getType()))
        self.jabberqueue(Presence(typ='subscribe',to=msobj.fromjid, frm=config.jid))

    def ms_send_online(self,fromjid,resource=None):
        if config.dumpProtocol: print 'xmpp_online:',fromjid,self.userlist[fromjid].roster
        fromstripped = fromjid
        if resource != None:
            fromjid = JID(fromjid)
            fromjid.setResource(resource)
        self.jabberqueue(Presence(to=fromjid,frm = config.jid))
        for msid in self.userlist[fromstripped].roster:
            if self.userlist[fromstripped].roster[msid][0] == 'available':
                self.jabberqueue(Presence(frm = '%s@%s/messenger' % (msid,config.jid), to = fromjid))

    def ms_send_offline(self,fromjid,resource=None,status=None):
        if config.dumpProtocol: print 'xmpp_offline:',fromjid,self.userlist[fromjid].roster
        fromstripped = fromjid
        if resource != None:
            fromjid = JID(fromjid)
            fromjid.setResource(resource)
        self.jabberqueue(Presence(to=fromjid,frm = config.jid, typ='unavailable',status=status))
        if self.userlist.has_key(fromstripped):
            for msid in self.userlist[fromstripped].roster:
                if self.userlist[fromstripped].roster[msid][0] == 'available':
                    self.jabberqueue(Presence(frm = '%s@%s/messenger' % (msid,config.jid), to = fromjid, typ='unavailable'))
                    self.jabberqueue(Presence(frm = '%s@%s/chat' % (msid,config.jid), to = fromjid, typ='unavailable'))

    #chat room functions
    def ms_chat_login(self,fromjid):
        msobj=self.userlist[fromjid]
        msobj.chatlogin=True
        if 'roomtojoin' in dir(msobj):
            msobj.msmsg_send_chatjoin(msobj.roomtojoin)
            del msobj.roomtojoin

    def ms_chat_roominfo(self,fromjid,info):
        msobj=self.userlist[fromjid]
        if not msobj.roomlist.has_key(info['room']):
            msobj.roomlist[info['room']]={'byyid':{},'bynick':{},'info':info}
            self.jabberqueue(Presence(frm = '%s@%s' %(RoomEncode(info['room']),config.confjid),to=fromjid))
            text,xhtml = mshtmlformat(info['topic'])
            self.jabberqueue(Message(frm = '%s@%s' %(RoomEncode(info['room']),config.confjid),to=fromjid, typ='groupchat', subject=text))

    def ms_chat_join(self,fromjid,room,info):
        msobj=self.userlist[fromjid]
        if msobj.roomlist.has_key(room):
            if not msobj.roomlist[room]['byyid'].has_key(info['yip']):
                msobj.roomlist[room]['byyid'][info['yip']] = info
                if not info.has_key('nick'):
                    info['nick'] = info['yip']
                tojid = JID(fromjid)
                tojid.setResource(msobj.chatresource)
                #print info['yip'],msobj.username
                if info['yip'] == msobj.username:
                    jid = tojid
                    if config.dumpProtocol: print info['nick'], msobj.nick
                    if info['nick'] != msobj.nick:
                        # join room with wrong nick
                        p = Presence(to = tojid, frm = '%s@%s/%s' % (RoomEncode(room),config.confjid,msobj.nick))
                        p.addChild(node=MucUser(jid = jid, nick = msobj.nick, role = 'participant', affiliation = 'none'))
                        self.jabberqueue(p)
                        # then leave/change to the right nick
                        p = Presence(to = tojid, frm = '%s@%s/%s' % (RoomEncode(room),config.confjid,msobj.nick), typ='unavailable')
                        p.addChild(node=MucUser(jid = jid, nick = info['nick'], role = 'participant', affiliation = 'none', status = 303))
                        self.jabberqueue(p)
                        msobj.nick = info['nick']
                else:
                    jid = '%s@%s' % (info['yip'],config.jid)
                msobj.roomlist[room]['bynick'][info['nick']]= info['yip']
                self.jabberqueue(Presence(frm = '%s@%s/%s' % (RoomEncode(room),config.confjid,info['nick']), to = tojid, payload=[MucUser(role='participant',affiliation='none',jid = jid)]))

    def ms_chat_leave(self,fromjid,room,msid,nick):
        # Need to add some cleanup code
        #
        #
        msobj=self.userlist[fromjid]
        if msobj.roomlist.has_key(room):
            if msobj.roomlist[room]['byyid'].has_key(msid):
                del msobj.roomlist[room]['bynick'][msobj.roomlist[room]['byyid'][msid]['nick']]
                del msobj.roomlist[room]['byyid'][msid]
                jid = JID(fromjid)
                jid.setResource(msobj.chatresource)
                self.jabberqueue(Presence(frm = '%s@%s/%s' % (RoomEncode(room),config.confjid,nick), to= jid, typ = 'unavailable'))

    def xmpp_iq_version(self, con, event):
        fromjid = event.getFrom()
        to = event.getTo()
        id = event.getID()
        uname = platform.uname()
        m = Iq(to = fromjid, frm = to, typ = 'result', queryNS=NS_VERSION, payload=[Node('name',payload=VERSTR), Node('version',payload=version),Node('os',payload=('%s %s %s' % (uname[0],uname[2],uname[4])).strip())])
        m.setID(id)
        self.jabberqueue(m)
        raise NodeProcessed

    def xmpp_connect(self):
        connected = self.jabber.connect((config.mainServer,config.port))
        if config.dumpProtocol: print "connected:",connected
        while not connected:
            time.sleep(5)
            connected = self.jabber.connect((config.mainServer,config.port))
            if config.dumpProtocol: print "connected:",connected
        self.register_handlers()
        if config.dumpProtocol: print "trying auth"
        connected = self.jabber.auth(config.saslUsername,config.secret)
        if config.dumpProtocol: print "auth return:",connected
        return connected

    def xmpp_disconnect(self):
        for each in self.userlist.keys():
            msobj=self.userlist[each]
            if timerlist.has_key(msobj.alertpollobj):
                del timerlist[msobj.alertpollobj]
            del self.userlist[msobj.fromjid]
            if rdsocketlist.has_key(msobj.sock):
                del rdsocketlist[msobj.sock]
            if wrsocketlist.has_key(msobj.sock):
                del wrsocketlist[msobj.sock]
            msobj.sock.close()
            del msobj
        del rdsocketlist[self.jabber.Connection._sock]
        if wrsocketlist.has_key(self.jabber.Connection._sock):
            del wrsocketlist[self.jabber.Connection._sock]
        time.sleep(5)
        if not self.jabber.reconnectAndReauth():
            time.sleep(5)
            self.xmpp_connect()
        rdsocketlist[self.jabber.Connection._sock]='xmpp'

def loadConfig():
    configOptions = {}
    for configFile in config.configFiles:
        if os.path.isfile(configFile):
            xmlconfig.reloadConfig(configFile, configOptions)
            config.configFile = configFile
            return
    print "Configuration file not found. You need to create a config file and put it in one of these locations:\n    " + "\n    ".join(config.configFiles)
    sys.exit(1)

def logError():
    err = '%s - %s\n'%(time.strftime('%a %d %b %Y %H:%M:%S'),version)
    if logfile != None:
        logfile.write(err)
        traceback.print_exc(file=logfile)
        logfile.flush()
    sys.stderr.write(err)
    traceback.print_exc()
    sys.exc_clear()

def sigHandler(signum, frame):
    transport.offlinemsg = 'Signal handler called with signal %s'%signum
    if config.dumpProtocol: print 'Signal handler called with signal %s'%signum
    transport.online = 0

if __name__ == '__main__':
    if 'PID' in os.environ:
        config.pid = os.environ['PID']
    loadConfig()
    if config.pid:
        pidfile = open(config.pid,'w')
        pidfile.write(`os.getpid()`)
        pidfile.close()

    if config.compjid:
        xcp=1
    else:
        xcp=0
        config.compjid = config.jid

    if config.saslUsername:
        sasl = 1
    else:
        config.saslUsername = config.jid
        sasl = 0

    userfile = shelve.open(config.spoolFile)
    logfile = None
    if config.debugFile:
        logfile = open(config.debugFile,'a')

    if config.dumpProtocol:
        debug=['always', 'nodebuilder']
    else:
        debug=[]
    connection = xmpp.client.Component(config.compjid,config.port,debug=debug,domains=[config.jid,config.confjid],sasl=sasl,bind=config.useComponentBinding,route=config.useRouteWrap,xcp=xcp)
    transport = Transport(connection)
    if not transport.xmpp_connect():
        print "Could not connect to server, or password mismatch!"
        sys.exit(1)
    # Set the signal handlers
    signal.signal(signal.SIGINT, sigHandler)
    signal.signal(signal.SIGTERM, sigHandler)
    rdsocketlist[connection.Connection._sock]='xmpp'
    while transport.online:
        #print 'poll',rdsocketlist
        try:
            (i , o, e) = select.select(rdsocketlist.keys(),wrsocketlist.keys(),[],1)
        except socket.error:
            print "Bad Socket", rdsocketlist, wrsocketlist
            logError()
            transport.findbadconn()
            sys.exc_clear()
            (i , o, e) = select.select(rdsocketlist.keys(),wrsocketlist.keys(),[],1)
        except select.error:
            sys.exc_clear()
            (i , o, e) = select.select(rdsocketlist.keys(),wrsocketlist.keys(),[],1)
        for each in i:
            #print 'reading',each,rdsocketlist.has_key(each)
            if rdsocketlist.has_key(each):
                if rdsocketlist[each] == 'xmpp':
                    try:
                        connection.Process(1)
                    except IOError:
                        transport.xmpp_disconnect()
                    except:
                        logError()
                    if not connection.isConnected():  transport.xmpp_disconnect()
                else:
                    try:
                        rdsocketlist[each].Process()
                    except socket.error:
                        transport.ms_closed(rdsocketlist[each])
                    except:
                        logError()
        for each in o:
            #print 'writing',each,rdsocketlist.has_key(each),wrsocketlist.has_key(each)
            if rdsocketlist.has_key(each) and wrsocketlist.has_key(each):
                try:
                    if rdsocketlist[each] == 'xmpp':
                        while select.select([],[each],[])[1] and wrsocketlist[each] != []:
                            connection.send(wrsocketlist[each].pop(0))
                    else:
                        #print wrsocketlist
                        packet = wrsocketlist[each].pop(0)
                        if config.dumpProtocol: mslib.printpacket(packet)
                        each.send(packet)
                except socket.error:
                    transport.ms_closed(rdsocketlist[each])
                except:
                    logError()
                if wrsocketlist[each] == []:
                    del wrsocketlist[each]
            else:
                #print 'not writing',each,rdsocketlist.has_key(each),wrsocketlist.has_key(each)
                if rdsocketlist.has_key(each):
                    del rdsocketlist[each]
                if wrsocketlist.has_key(each):
                    del wrsocketlist[each]
        #delayed execution method modified from python-irclib written by Joel Rosdahl <joel@rosdahl.net>
        #and fixed up by Norman
        for each in timerlist.keys():
            current_time = time.time()
            if timerlist[each] < current_time:
                try:
                    timerlist[each] = current_time + each[0]
                    apply(each[1],each[2])
                except:
                    logError()
    for each in (x for x in transport.userlist.keys()):
        transport.userlist[each].connok = True
        transport.ms_send_offline(each, status = transport.offlinemsg)
    del rdsocketlist[connection.Connection._sock]
    if wrsocketlist.has_key(connection.Connection._sock):
        while wrsocketlist[connection.Connection._sock] != []:
            connection.send(wrsocketlist[connection.Connection._sock].pop(0))
        del wrsocketlist[connection.Connection._sock]
    userfile.close()
    connection.disconnect()
    if config.pid:
        os.unlink(config.pid)
    if logfile:
        logfile.close()
    if transport.restart:
        args=[sys.executable]+sys.argv
        if os.name == 'nt': args = ["\"%s\"" % a for a in args]
        if config.dumpProtocol: print sys.executable, args
        os.execv(sys.executable, args)
