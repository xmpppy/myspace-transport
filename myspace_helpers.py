#! /usr/bin/env python

# MySpace Definitions
from types import *
import struct

#Packet Types - http://developer.pidgin.im/wiki/MsimProtocolSpec
MS_loginchallenge = 'lc'    # login challenge
MS_loginresponse = 'login2' # login challenge response
MS_msg = 'bm'               # buddy message
MS_msg_mappings = {'im':1,  #  Instant Message
    'status':100,           #  Incoming Status Message
    'action':121,           #  Action Message
    'media':122,            #  Media Message
    'profile':124,          #  Profile Message
    'miranda':200}          #  The Miranda IM plugin uses this to "send miranda + plugin version information as is done with many other protocols"
MS_msg_mappings_reverse = dict(zip(MS_msg_mappings.values(),MS_msg_mappings.keys()))
MS_msg_im = 1               #  Instant Message
MS_msg_status = 100         #  Incoming Status Message
MS_msg_action = 121         #  Action Message
MS_msg_action_typing = '%typing%'
MS_msg_action_stoptyping = '%stoptyping%'
MS_msg_action_zap_prefix = '!!!ZAP_SEND!!!=RTE_BTN_ZAPS_'
MS_msg_action_zap_prefix_len = len(MS_msg_action_zap_prefix)
MS_msg_action_zap_mappings = (
    ("zap","zapped","Zapping"),
    ("whack","whacked","Whacking"),
    ("torch","torched","Torching"),
    ("smooch","smooched","Smooching"),
    ("hug","hugged","Hugging"),
    ("bslap","b'slapped","B'Slapping"),
    ("goose","goosed","Goosing"),
    ("hi five","hi-fived","Hi-fiving"),
    ("punk","punk'd","Punking"),
    ("raspberry","raspberried","Raspberry'ing"))
MS_msg_media = 122          #  Media Message
MS_msg_profile = 124        #  Profile Message
MS_msg_miranda = 200        #  The Miranda IM plugin uses this to "send miranda + plugin version information as is done with many other protocols"
MS_setstatus = 'status'     # Set Status Message
MS_status_offline = 0
MS_status_online = 1
MS_status_idle = 2
MS_status_away = 5
MS_keeplaive = 'ka'         # Keepalive
MS_rosteradd = 'addbuddy'   # Add Buddy
MS_rosterdel = 'delbuddy'   # Delete Buddy
MS_blocklist = 'blocklist'  # Block List
MS_getinfo = 'getinfo'      # Get Info
MS_setinfo = 'setinfo'      # Set Info
MS_persist_req = 'persist'  # Persist Message Request
MS_persist_rep = 'persistr' # Persist Message Response
MS_persist_mappings = {
    'list_contacts':(1,0,1),
    'get_contact_info':(1,0,2),
    'get_my_info':(1,1,4),
    'lookup_im_info':(1,1,7),
    'list_groups':(1,2,6),
    'lookup_user_by_id':(1,4,3),
    'lookup_my_info':(1,4,5),
    'lookup_user_by_string':(1,5,7),
    'check_mail':(1,7,18),
    'web_challange':(1,17,26),
    'get_user_song':(1,21,28),
    'server_info':(1,512,20),
    'set_username':(2,9,14),
    'add_all_friends':(2,14,21),
    'set_contact_info':(514,0,9),
    'set_user_pref':(514,1,10),
    'invite_user':(514,16,25),
    'del_buddy':(515,0,8)}
MS_persist_mappings_reverse = dict(zip(MS_persist_mappings.values(),MS_persist_mappings.keys()))
MS_persist_UserID = 'UserID'
MS_persist_Email = 'Email'
MS_persist_UserName = 'UserName'
MS_persist_Deleted = 'Deleted'
MS_persist_mail = {
    "Mail":("mail messages","http://messaging.myspace.com/index.cfm?fuseaction=mail.inbox"), 
    "BlogComment":("blog comments","http://blog.myspace.com/index.cfm?fuseaction=blog"), 
    "ProfileComment":("profile comments","http://home.myspace.com/index.cfm?fuseaction=user"), 
    "FriendRequest":("friend requests","http://messaging.myspace.com/index.cfm?fuseaction=mail.friendRequests"), 
    "PictureComment":("picture comments","http://home.myspace.com/index.cfm?fuseaction=user")}

MS_error = 'error'          # Error Message
MS_logout = 'logout'        # Logout

MySpaceSep = '\\final\\'
MySpaceSepLen = len(MySpaceSep)

def msmsg_mkmsg(*lst):
    return str(myspace_message(lst))

def msmsg_demsg(text):
    eod = text.find(MySpaceSep)
    if eod != -1:
        eop = eod + MySpaceSepLen
        msg = myspace_message(text[:eop])
        return eop, msg
    return 0, None

class myspace_message(object):

    def __init__(self, data=None):
        self._keys = []
        self._data = {}
        if isinstance(data, basestring):
            self.init_from_string(data)
            if str(self) != data:
                raise Exception('Invalid decode: (%s) became (%s)' % (data, str(self)))
        elif isinstance(data, tuple):
            self.init_from_tuple(data)
        elif data == None:
            pass
        else:
            raise Exception('Invalid message init parameter')

    def init_from_string(self, packet):
        if packet[0] != '\\':
            raise Exception('Invalid packet data: %s' % packet)
        while packet:
            s1 = packet.find('\\',1)
            if s1 == -1:
                raise Exception('Missing packet key-value pair')
            s2 = packet.find('\\',s1+1)
            key = packet[1:s1]
            if s2 != -1:
                value = packet[s1+1:s2]
                packet = packet[s2:]
            else:
                if packet != MySpaceSep: raise Exception('Invalid packet termination')
                packet = None
                break
            self._keys.append(key)
            self._data[key] = value
        if packet: raise Exception('Invalid packet termination')

    def init_from_tuple(self, tuple):
        for typ, key, value in tuple:
            getattr(self, 'set_' + typ)(key, value)

    def __str__(self):
        lst = ['\\%s\\%s' % (key,self._data[key]) for key in self._keys]
        return ''.join(lst) + MySpaceSep

    def get_op(self):
        return self._keys[0]
    op = property(get_op, None)

    def get_str(self, key):
        if key not in self._data: return
        return self._data[key].replace('/2','\\').replace('/1','/')

    def set_str(self, key, value):
        if key not in self._data: self._keys.append(key)
        self._data[key] = value.replace('/','/1').replace('\\','/2')

    def get_int(self, key):
        if key not in self._data: return
        return int(self._data[key])

    def set_int(self, key, value):
        if key not in self._data: self._keys.append(key)
        self._data[key] = str(value)

    def get_bool(self, key):
        if key not in self._data: return
        return True

    def set_bool(self, key, value):
        if key not in self._data: self._keys.append(key)
        if not value: raise Exception('Boolean values can only be true')
        self._data[key] = ''

    def get_bin(self, key):
        if key not in self._data: return
        return self._data[key].decode('base64')

    def set_bin(self, key, value):
        if key not in self._data: self._keys.append(key)
        self._data[key] = str(value).encode('base64').replace('\n','')

    def get_list(self, key):
        if key not in self._data: return
        return [x.replace('/3', '|').replace('/2','\\').replace('/1','/') for x in self._data[key].split('|')]

    def set_list(self, key, list):
        if key not in self._data: self._keys.append(key)
        self._data[key] = '|'.join((x.replace('/','/1').replace('\\','/2').replace('|','/3') for x in list))

    def get_dict(self, key):
        if key not in self._data: return
        if self._data[key]:
            return ((y[0].replace('/2','\\').replace('/1','/'),y[1].replace('/2','\\').replace('/1','/')) for y in (x.split('=',1) for x in self._data[key].split('\x1c')))
        else:
            return ()

    def set_dict(self, key, dict):
        if key not in self._data: self._keys.append(key)
        self._data[key] = '\x1c'.join(('%s=%s' % (x[0].replace('/','/1').replace('\\','/2'), x[1].replace('/','/1').replace('\\','/2')) for x in dict))
