#! /usr/bin/env python

# MySpace driver test script.
import myspace_auth
from myspace_helpers import *
import socket, time
import avatar
import re
import random


def printpacket(packet):
    size,msg = msmsg_demsg(packet)
    print 'send', repr(str(msg))


# MySpace Functions
class MySpaceCon(object):
    rbuf = ''
    alertpollobj = None
    session = 0
    uid = 0
    host = 'im.myspace.akadns.net'
    hostlist = socket.gethostbyname_ex(host)[2]
    port = 1863
    version = 697
    default_timeout = 30
    sock = None
    # a dictionary of groups and members
    buddylist = {}
    # Tuple by availabilaity, show value, status message
    roster = {}
    handlers = {}
    # login -- on sucessful login
    # loginfail -- on login failure

    def __init__(self, username, password, fromjid,fromhost,dumpProtocol):
        self.username = username
        self.password = password
        self.fromhost = fromhost
        self.fromjid = fromjid
        self.roster = {}
        self.buddylist = {}
        self.away = False
        #variables for public MUC
        self.alias = username
        #Each room has a list of participants in the form of {username:(alias,state,statemsg)}
        self.roomlist = {}
        self.roomnames = {} #Dictionary entry for *NAUGHTY* clients that lowercase the JID
        self.chatlogin = False
        self.chatresource = None
        #login junk
        self.connok = False
        self.conncount = 0
        self.callbacks = {}
        self.resources = {}
        self.xresources = {}
        self.offset = int(random.random()*len(self.hostlist))
        self.dumpProtocol = dumpProtocol
        self.lastrid = 1
        self.sendqueue = []
        self.mailstatus = {}
        self.contactdetails = {}

    # utility methods
    def connect(self,timeout=10):
        self.connok=False
        while self.conncount != len(self.hostlist):
            if self.dumpProtocol: print "conncount", self.conncount
            self.sock = None
            self.sock = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
            self.sock.settimeout(timeout)
            self.sock.bind((self.fromhost,0))
            try:
                if not self.sock.connect((self.hostlist[(self.offset+self.conncount)%len(self.hostlist)],self.port)):
                    self.conncount = self.conncount + 1
                    return self.sock
            except socket.error:
                self.conncount = self.conncount + 1
                pass
        return None

    def send(self, packet):
        if packet[0] != '\\':
            raise Exception('Invalid packet data: %s' % repr(packet))
        if self.dumpProtocol: 
            size,msg = msmsg_demsg(packet)
            print 'rawsend', repr(str(msg))
        return self.sock.send(packet)

    def send_msg(self, *data):
        if self.session == 0:
            return self.sendqueue.append(data)
        if data[0][1] == MS_persist_req:
            if data[1][1] != 'uid':
                raise Exception('uid missing!')
            if data[1][2] == 0:
                if self.uid == 0:
                    return self.sendqueue.append(data)
                data = data[0:1] + (('int','uid',self.uid),) + data[2:]
        data = data[0:1] + (('int','sesskey',self.session),) + data[1:]
        return self.send(msmsg_mkmsg(*data))

    def moreservers(self):
        if self.conncount < len(self.hostlist):
            if self.dumpProtocol: print "more servers %s %s" % (len(self.hostlist),self.conncount)
            return True
        else:
            return False

    # decoding handlers
    def msmsg_challenge(self,msg):
        # send authentication challenge responce
        stage = msg.get_int('lc')
        if stage == 1:
            ip_list = [x[4][0] for x in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM)]
            response = myspace_auth.process_auth(self.username,self.password,msg.get_bin('nc'),ip_list)
            self.send(msmsg_mkmsg(
                ('int',MS_loginresponse,196610),
                ('str','username',self.username),
                ('bin','response',response),
                ('int','clientver',self.version),
                ('int','reconn',0),
                ('int','status',100),
                ('int','id',1)))
        elif stage == 2:
            self.session = msg.get_int('sesskey')
            self.uid = msg.get_int('userid')
            self.msmsg_send_persist_req('list_contacts')
            for data in self.sendqueue:
                self.send_msg(*data)
            self.sendqueue = None
        else:
            raise Exception('unexpected login challenge stage: %s' % stage)

    def msmsg_persist_rep(self,msg):
        cmd = msg.get_int('cmd')
        dsn = msg.get_int('dsn')
        lid = msg.get_int('lid')
        rid = msg.get_int('rid')
        key = (cmd&~256,dsn,lid)
        ckey = (cmd&~256,dsn,lid,rid)
        if self.callbacks.has_key(ckey):
            callback = self.callbacks[ckey][0]
            del self.callbacks[ckey]
        else:
            callback = None
        #if self.dumpProtocol: print 'persist_rep:',key
        if MS_persist_mappings_reverse.has_key(key):
            getattr(self, 'msmsg_persist_rep_' + MS_persist_mappings_reverse[key])(msg, callback)
        else:
            if self.dumpProtocol: print 'unknown persist reply:',cmd,dsn,lid

    def msmsg_persist_rep_list_contacts(self,msg,callback):
        body = msg.get_dict('body')
        contacts = []
        contact = {}
        for entry in body:
            if contact.has_key(entry[0]):
                contacts.append(contact)
                contact = {}
            contact[entry[0]] = entry[1]
        contacts.append(contact)
        for contact in contacts:
            contactid = contact['ContactID']
            group = contact['GroupName']
            if not self.buddylist.has_key(group):
                self.buddylist[group] = []
            self.buddylist[group].append(contactid)
            if not self.roster.has_key(contactid):
                self.roster[contactid]=('unavailable',None, None)
            self.msmsg_send_persist_req('lookup_user_by_id', ((MS_persist_UserID, contactid),), self.msmsg_persist_rep_list_contacts_callback_nickname)
        print 'roster:',self.roster
        print 'buddylist:',self.buddylist
        if self.handlers.has_key('login'):
            self.handlers['login'](self)

    def msmsg_persist_rep_list_contacts_callback_nickname(self, contactid):
        if self.roster.has_key(contactid):
            mode, typ, status = self.roster[contactid]
            if mode == 'available':
                if self.handlers.has_key('online'):
                    self.handlers['online'](self,contactid)
            else:
                if self.handlers.has_key('offline'):
                    self.handlers['offline'](self,contactid)

    def msmsg_persist_rep_get_contact_info(self,msg,callback):
        if self.dumpProtocol: print 'get_contact_info:',dict(msg.get_dict('body'))

    def msmsg_persist_rep_lookup_user_common(self,msg,callback):
        body = dict(msg.get_dict('body'))
        uid = None
        if body.has_key(MS_persist_UserID) and not body.has_key(MS_persist_Deleted):
            uid = body[MS_persist_UserID]
        if uid:
            self.contactdetails[uid] = body
        if callback:
            callback(uid)

    def msmsg_persist_rep_lookup_user_by_id(self,msg,callback):
        if self.dumpProtocol: print 'lookup_user_by_id:',dict(msg.get_dict('body'))
        self.msmsg_persist_rep_lookup_user_common(msg,callback)

    def msmsg_persist_rep_lookup_user_by_string(self,msg,callback):
        if self.dumpProtocol: print 'lookup_user_by_string:',dict(msg.get_dict('body'))
        self.msmsg_persist_rep_lookup_user_common(msg,callback)

    def msmsg_persist_rep_server_info(self,msg,callback):
        self.serverinfo = dict(msg.get_dict('body'))
        if self.dumpProtocol: print 'serverinfo:',self.serverinfo

    def msmsg_persist_rep_check_mail(self,msg,callback):
        newmailstatus = dict(msg.get_dict('body'))
        notifications = []
        for status in MS_persist_mail.keys():
            if newmailstatus.has_key(status) and not self.mailstatus.has_key(status):
                notifications.append(MS_persist_mail[status])
        self.mailstatus = newmailstatus
        if self.handlers.has_key('mailalert'):
            self.handlers['mailalert'](self, notifications)

    def msmsg_persist_rep_web_challange(self,msg,callback):
        if self.dumpProtocol: print 'web_challange_data:',tuple(msg.get_dict('body'))

    def msmsg_buddy_message(self,msg):
        bm = msg.get_int('bm')
        if MS_msg_mappings_reverse.has_key(bm):
            getattr(self, 'msmsg_buddy_message_' + MS_msg_mappings_reverse[bm])(msg)
        else:
            if self.dumpProtocol: print 'unknown buddy message:',cmd

    def msmsg_buddy_message_im(self,msg):
        frm = msg.get_int('f')
        msg = msg.get_str('msg')
        if self.handlers.has_key('message'):
            self.handlers['message'](self, frm, msg)

    def msmsg_buddy_message_status(self,msg):
        frm = str(msg.get_int('f'))
        msg = dict(zip(*[iter(msg.get_list('msg')[1:])]*2))

        if self.dumpProtocol: print 'message status:',msg
        if msg['s'] == '0':
            typ = 'offline'
        elif msg['s'] == '1':
            typ = None
        elif msg['s'] == '2':
            typ = 'idle'
        elif msg['s'] == '5':
            typ = 'away'
        status = msg['ss']

        if typ != 'offline':
            self.roster[frm]=('available', typ, status)
            if not self.resources.has_key(frm):
                self.resources[frm]=[]
            if self.resources.has_key(frm):
                if not 'messenger' in self.resources[frm]:
                    self.resources[frm].append('messenger')
            if self.handlers.has_key('online'):
                self.handlers['online'](self,frm)
        else:
            if self.resources.has_key(frm):
                if 'messenger' in self.resources[frm]:
                    self.resources[frm].remove('messenger')
                    if self.handlers.has_key('offline'):
                        self.handlers['offline'](self,frm)
            if not self.resources.has_key(frm) or self.resources[frm] == []:
                self.roster[frm]=('unavailable', None, None)


    def msmsg_buddy_message_action(self,msg):
        frm = msg.get_int('f')
        msg = msg.get_str('msg')
        if msg == MS_msg_action_typing:
            if self.handlers.has_key('notify'):
                self.handlers['notify'](self,frm,1)
        elif msg == MS_msg_action_stoptyping:
            if self.handlers.has_key('notify'):
                self.handlers['notify'](self,frm,0)
        elif msg.startswith(MS_msg_action_zap_prefix):
            zap = int(msg[MS_msg_action_zap_prefix_len:])
            msg = '/me has %s you!' % MS_msg_action_zap_mappings[zap][1]
            if self.handlers.has_key('message'):
                self.handlers['message'](self, frm, msg)
        else:
            if self.dumpProtocol: print 'unknown action message:',msg

    def msmsg_buddy_message_media(self,msg):
        pass

    def msmsg_buddy_message_profile(self,msg):
        pass

    def msmsg_buddy_message_miranda(self,msg):
        pass

    def ymsg_avatar(self,hdr,pay):
        if pay[0].has_key(4):
            for each in pay:
                if pay[each].has_key(4):
                    if pay[each].has_key(198):
                        if pay[each][198] == '1' and pay[each].has_key(197):
                            b = avatar.getavatar(pay[each][197], self.dumpProtocol)
                            if b != None and self.handlers.has_key('avatar'):
                                self.handlers['avatar'](self,pay[each][4],b)
                        elif pay[each][198] == '0':
                            if self.handlers.has_key('avatar'):
                                self.handlers['avatar'](self,pay[each][4],None)

    def ymsg_imvset(self,hdr,pay):
        if pay[0].has_key(7):
            for each in pay:
                if pay[each].has_key(13):
                    if pay[each][13] == '1':
                        if pay[each].has_key(7):
                            self.roster[pay[each][7]]=('available', None, None)
                            if self.handlers.has_key('online'):
                                self.handlers['online'](self,pay[each][7])

    def ymsg_notification(self,hdr,pay):
        if pay[0].has_key(20):
            url = pay[0][20]
        else:
            url = None
        if pay[0].has_key(14):
            desc = pay[0][14]
        else:
            desc = None
        if self.handlers.has_key('calendar'):
            self.handlers['calendar'](self,url,desc)

    def ymsg_email(self,hdr,pay):
        if pay[0].has_key(43):
            fromtxt = pay[0][43]
        else:
            fromtxt = None
        if pay[0].has_key(42):
            fromaddr = pay[0][42]
        else:
            fromaddr = None
        if pay[0].has_key(18):
            subj = pay[0][18]
        else:
            subj = None
        if subj != None or fromaddr != None or fromtxt != None:
            if self.handlers.has_key('email'):
                self.handlers['email'](self,fromtxt,fromaddr,subj)


    def ymsg_roster(self,hdr,pay):
        if pay[0].has_key(3):
            if pay[0].has_key(14):
                msg = pay[0][14]
            else:
                msg = ''
            if self.handlers.has_key('subscribe'):
                self.handlers['subscribe'](self,pay[0][3],msg)
        self.ymsg_online(hdr,pay)

    def ymsg_ping(self, hdr, pay):
        self.secpingfreq = 60
        self.pripingfreq = 4
        if pay[0].has_key(143):
            self.secpingfreq = float(pay[0][143])
        else:
            self.secpingfreq = None
        if pay[0].has_key(144):
            self.pripingfreq = float(pay[0][144])
        else:
            self.pripingfreq = None
        if self.handlers.has_key('ping'):
            self.handlers['ping'](self)

    def ymsg_reqroom(self, hdr,pay):
        if self.dumpProtocol: print "got reqroom"
        if self.handlers.has_key('reqroom'):
            self.handlers['reqroom'](self.fromjid)

    def ymsg_conflogon(self,hdr,pay):
        if self.handlers.has_key('conflogon'):
            self.handlers['conflogon']()

    def ymsg_joinroom(self,hdr,pay):
        # Do generic room information stuff
        room = None
        roominfo = {}
        if pay[0].has_key(104):
            roominfo['room'] = pay[0][104]
            room = pay[0][104]
        if pay[0].has_key(105):
            roominfo['topic'] = pay[0][105]
        if pay[0].has_key(108):
            roominfo['members'] = pay[0][108]
        if roominfo != {}:
            if self.handlers.has_key('roominfo') and room != None:
                self.handlers['roominfo'](self.fromjid, roominfo)
        # Do room member stuff
        for b in pay:
            each = pay[b]
            a = {}
            if each.has_key(109):
                a['yip']=each[109]
            if each.has_key(141):
                a['nick']=each[141]
            if each.has_key(113):
                a['ygender'] = each[113]
            if each.has_key(110):
                a['age'] = each[110]
            if each.has_key(142):
                a['location'] = each[142]
                a['location'] = each[142]
            if self.handlers.has_key('chatjoin') and room != None:
                self.handlers['chatjoin'](self.fromjid,room,a)

    def ymsg_leaveroom(self,hdr,pay):
        room = None
        if pay[0].has_key(104):
            room = pay[0][104]
        for a in pay:
            each = pay[a]
            if each.has_key(109):
                yid = each[109]
            else:
                yid = None
            if each.has_key(141):
                nick = each[141]
            else:
                nick = yid
            if self.handlers.has_key('chatleave'):
                self.handlers['chatleave'](self.fromjid,room,yid,nick)


    def ymsg_roommsg(self, hdr, pay):
        if pay[0].has_key(109):
            if pay[0].has_key(124):
                if pay[0][124]=='2':
                    msg = '/me '+pay[0][117]
                else:
                    msg = pay[0][117]
            else:
                msg = pay[0][117]
            if hdr[4] == 1:
                if self.handlers.has_key('roommessage'):
                    self.handlers['roommessage'](self, pay[0][109], pay[0][104], msg)
            elif hdr[4] == 2:
                if self.handlers.has_key('roommessagefail'):
                    self.handlers['roommessagefail'](self, pay[0][109], pay[0][104], msg)

    def msmsg_send_persist_req(self,request,body=None,callback=None,timeout=None):
        cmd, dsn, lid = MS_persist_mappings[request]
        self.lastrid += 1
        self.send_msg(
            ('int',MS_persist_req,1),
            ('int','uid',self.uid),
            ('int','cmd',cmd),
            ('int','dsn',dsn),
            ('int','lid',lid),
            ('int','rid',self.lastrid),
            ('dict','body',body or ()))
        if callback:
            ckey = (cmd&~256,dsn,lid,self.lastrid)
            self.callbacks[ckey] = (callback, time.time() + (timeout or self.default_timeout))
        return self.lastrid

    def msmsg_send_lookup_user(self,userinfo,callback=None,timeout=None):
        if userinfo.isdigit():
            request = 'lookup_user_by_id'
            key = MS_persist_UserID
        elif userinfo.find('@') > -1:
            request = 'lookup_user_by_string'
            key = MS_persist_Email
        else:
            request = 'lookup_user_by_string'
            key = MS_persist_UserName
        return self.msmsg_send_persist_req(request, ((key, userinfo),), callback, timeout)

    def msmsg_send_check_mail(self):
        return self.msmsg_send_persist_req('check_mail')

    def msmsg_send_addbuddy(self, profileid, reason='', group='Contacts'):
        self.send_msg(
            ('bool',MS_rosteradd,True),
            ('int','newprofileid',profileid),
            ('str','reason',reason))
        self.send_msg(
            ('bool',MS_blocklist,True),
            ('list','idlist',('b-',profileid,'a+',profileid)))
        self.msmsg_send_persist_req('set_contact_info',(
            ('ContactID',profileid),
            ('GroupName',group),
            ('Position','1000'),
            ('Visibility','1'),
            ('NameSelect','0')))
        if not self.buddylist.has_key(group):
            self.buddylist[group] = []
        self.buddylist[group].append(profileid)
        if self.dumpProtocol: print 'roster:',self.roster
        if self.dumpProtocol: print 'buddylist:',self.buddylist

    def msmsg_send_delbuddy(self, profileid, reason=''):
        self.send_msg(
            ('bool',MS_rosterdel,True),
            ('int','delprofileid',profileid))
        self.msmsg_send_persist_req('del_buddy',(
            ('ContactID',profileid),))
        self.send_msg(
            ('bool',MS_blocklist,True),
            ('list','idlist',('a-',profileid,'b+',profileid)))
        del self.roster[profileid]
        for group in self.buddylist:
            if profileid in group:
                group.remove(profileid)
        if self.dumpProtocol: print 'roster:',self.roster
        if self.dumpProtocol: print 'buddylist:',self.buddylist

    def ymsg_send_conflogon(self):
        if self.dumpProtocol: print "cookies",self.cookies
        pay = ymsg_mkargu({0:self.username,1:self.username,6: '%s; %s' % (self.cookies[0].replace('\t','=').split(';')[0],self.cookies[1].replace('\t','=').split(';')[0])})
        hdr = ymsg_mkhdr(self.version,len(pay),Y_confon,0x5a55aa55,self.session)
        return hdr+pay

    def ymsg_send_conflogoff(self):
        pay = ymsg_mkargu({0:self.username,1:self.username})
        hdr = ymsg_mkhdr(self.version,len(pay),Y_confoff,0,self.session)
        return hdr+pay

    def ymsg_send_chatlogin(self,alias):
        if alias == None:
            alias == self.username
        self.alias = alias
        pay = ymsg_mkargu({109:self.username,1:self.username,6:'abcde'})
        hdr = ymsg_mkhdr(self.version, len(pay), Y_reqroom,0,self.session)
        return hdr+pay

    def ymsg_send_chatlogout(self):
        pay = ymsg_mkargu({1:self.username})
        hdr = ymsg_mkhdr(self.version, len(pay), Y_chatlogout, 0, self.session)
        return hdr+pay

    def ymsg_send_chatjoin(self,room):
        self.roomlist[room]={'byyid':{},'bynick':{},'info':{}}
        pay = ymsg_mkargu({1:self.username, 62:'2',104:room})
        hdr = ymsg_mkhdr(self.version,len(pay), Y_joinroom,0,self.session)
        return hdr+pay

    def ymsg_send_chatleave(self,room):
        pay = ymsg_mkargu({1:self.username,104:room})
        hdr = ymsg_mkhdr(self.version,len(pay), Y_leaveroom, 1, self.session)
        return hdr+pay

    def ymsg_send_roommsg(self,room,msg, type = 0):
        pay = ymsg_mkargu({1:self.username,104:room,117:msg,124:type})
        hdr = ymsg_mkhdr(self.version,len(pay), Y_chtmsg,1,self.session)
        return hdr+pay

    def msmsg_send_message(self, nick, msg):
        self.send_msg(
            ('int',MS_msg,MS_msg_im),
            ('int','t',nick),
            ('int','cv',self.version),
            ('str','msg',msg))

    def msmsg_send_action(self, nick, action):
        self.send_msg(
            ('int',MS_msg,MS_msg_action),
            ('int','t',nick),
            ('int','cv',self.version),
            ('str','msg',action))

    def msmsg_send_status(self, show = None, message = None, location = None):
        status = MS_status_offline
        if show == None:
            status = MS_status_online
        elif show == 'away':
            status = MS_status_idle
        elif show == 'dnd':
            status = MS_status_away
        if self.dumpProtocol: print "send_online",status
        self.send_msg(
            ('int',MS_setstatus,status),
            ('str','statstring',message or ''),
            ('str','locstring',location or ''))

    def msmsg_error(self,msg):
        
        # Function to determine the error type and then send that to the main process
        # All the error cases are shown with a different code in the err field. Unfortunately we cannot process image ID at this time.
        err = msg.get_int('err')
        if msg.get_bool('fatal'):
            handler = 'loginfail'
        else:
            handler = 'servicemessage'
        reason = None
        if err == 259:
            #The supplied email address is invalid
            reason = 'badusername'
        elif err == 260:
            #The password provided is incorrect
            reason = 'badpassword'
        elif err == 6:
            #This profile has been disconnected by another login
            reason = 'disconnected'
        elif err == 1539:
            #The profile requested is already a buddy
            reason = 'alreadyabuddy'
        elif err == 2817:
            #The buddy to be deleted is not a buddy
            reason = 'notabuddy'
        if self.handlers.has_key(handler):
            self.handlers[handler](self,reason)

    def Process(self):
        r = self.sock.recv(1024)
        #print r
        if len(r) != 0:
            self.rbuf = '%s%s'%(self.rbuf,r)
        else:
            # Broken Socket Case.
            if self.handlers.has_key('closed'):
                self.handlers['closed'](self)
        while len(self.rbuf) >= 20:
            size,msg = msmsg_demsg(self.rbuf)
            #print s, len(self.rbuf)
            if size:
                try:
                    if self.dumpProtocol: print 'recv', size, repr(str(msg)), len(self.rbuf)
                    if msg.op == MS_loginchallenge:
                        self.msmsg_challenge(msg)
                    elif msg.op == MS_persist_rep:
                        self.msmsg_persist_rep(msg)
                    elif msg.op == MS_msg:
                        self.msmsg_buddy_message(msg)
                    elif msg.op == MS_error:
                        self.msmsg_error(msg)
                    elif msg.op == MS_keeplaive:
                        if self.dumpProtocol: print 'keepalive'
                    else:
                        if self.dumpProtocol: print 'unknown operation:', msg.op
                finally:
                    #print "remove packet"
                    self.rbuf = self.rbuf[size:]

            else:
                break

if __name__ == '__main__':
    ms = MySpaceCon('user@example.com','password','jid','',True)
    while not ms.connect(10):
        print 'sleep'
        time.sleep(5)

    print "connected ", ms.sock

    while 1:
        ms.Process()
