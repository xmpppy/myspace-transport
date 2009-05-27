# $Id: adhoc.py,v 1.1 2008-01-08 04:23:52 norman Exp $

import sys, xmpp
from xmpp.protocol import *
import config
from xep0133 import *
from myspace_helpers import MS_msg_action_zap_mappings, MS_msg_action_zap_prefix

class AdHocCommands:

    def __init__(self, userfile):
        self.userfile = userfile

    def PlugIn(self, transport):
        self.commands = xmpp.commands.Commands(transport.disco)
        self.commands.PlugIn(transport.jabber)

        # jep-0133 commands:
        transport.cmdonlineusers = Online_Users_Command(transport.userlist,jid=config.jid)
        transport.cmdonlineusers.plugin(self.commands)
        transport.cmdactiveusers = Active_Users_Command(transport.userlist,jid=config.jid)
        transport.cmdactiveusers.plugin(self.commands)
        transport.cmdregisteredusers = Registered_Users_Command(self.userfile,jid=config.jid)
        transport.cmdregisteredusers.plugin(self.commands)
        transport.cmdeditadminusers = Edit_Admin_List_Command(jid=config.jid)
        transport.cmdeditadminusers.plugin(self.commands)
        transport.cmdrestartservice = Restart_Service_Command(transport,jid=config.jid)
        transport.cmdrestartservice.plugin(self.commands)
        transport.cmdshutdownservice = Shutdown_Service_Command(transport,jid=config.jid)
        transport.cmdshutdownservice.plugin(self.commands)

        # transport wide commands:
        transport.cmdconnectusers = Connect_Registered_Users_Command(self.userfile)
        transport.cmdconnectusers.plugin(self.commands)

        # per contact commands:
        transport.cmdzapcontact = ZAP_Contact_Command(transport)
        transport.cmdzapcontact.plugin(self.commands)

class Connect_Registered_Users_Command(xmpp.commands.Command_Handler_Prototype):
    """This is the register users command"""
    name = "connect-users"
    description = 'Connect all registered users'
    discofeatures = [xmpp.commands.NS_COMMANDS]

    def __init__(self,userfile):
        """Initialise the command object"""
        xmpp.commands.Command_Handler_Prototype.__init__(self,config.jid)
        self.initial = { 'execute':self.cmdFirstStage }
        self.userfile = userfile

    def _DiscoHandler(self,conn,request,type):
        """The handler for discovery events"""
        if request.getFrom().getStripped() in config.admins:
            return xmpp.commands.Command_Handler_Prototype._DiscoHandler(self,conn,request,type)
        else:
            return None

    def cmdFirstStage(self,conn,request):
        """Build the reply to complete the request"""
        if request.getFrom().getStripped() in config.admins:
            for each in self.userfile.keys():
                conn.send(Presence(to=each, frm = config.jid, typ = 'probe'))
                if self.userfile[each].has_key('servers'):
                    for server in self.userfile[each]['servers']:
                        conn.send(Presence(to=each, frm = '%s@%s'%(server,config.jid), typ = 'probe'))
            reply = request.buildReply('result')
            form = DataForm(typ='result',data=[DataField(value='Command completed.',typ='fixed')])
            reply.addChild(name='command',namespace=NS_COMMANDS,attrs={'node':request.getTagAttr('command','node'),'sessionid':self.getSessionID(),'status':'completed'},payload=[form])
            self._owner.send(reply)
        else:
            self._owner.send(Error(request,ERR_FORBIDDEN))
        raise NodeProcessed

class ZAP_Contact_Command(xmpp.commands.Command_Handler_Prototype):
    """This is the ZAP contact command"""
    name = "zap-contact"
    description = 'Send a zap'
    discofeatures = [xmpp.commands.NS_COMMANDS]
    zaplist = [x[0] for x in MS_msg_action_zap_mappings]
    zapindexes = {}
    for i in range(len(zaplist)):
        zapindexes[zaplist[i]] = i

    def __init__(self,transport,jid=''):
        """Initialise the command object"""
        xmpp.commands.Command_Handler_Prototype.__init__(self,jid)
        self.initial = {'execute':self.cmdFirstStage }
        self.transport = transport

    def _DiscoHandler(self,conn,event,type):
        """The handler for discovery events"""
        fromstripped = event.getFrom().getStripped().encode('utf8')
        if self.transport.userlist.has_key(fromstripped):
            return xmpp.commands.Command_Handler_Prototype._DiscoHandler(self,conn,event,type)
        else:
            return None

    def cmdFirstStage(self,conn,request):
        """Set the session ID, and return the form containing the zap options"""
        fromstripped = request.getFrom().getStripped().encode('utf8')
        if self.transport.userlist.has_key(fromstripped):
           # Setup session ready for form reply
           session = self.getSessionID()
           self.sessions[session] = {'jid':request.getFrom(),'actions':{'cancel':self.cmdCancel,'next':self.cmdSecondStage,'execute':self.cmdSecondStage}}
           # Setup form with existing data in
           reply = request.buildReply('result')
           form = DataForm(title='Zap',data=['Pick a zap', DataField(desc='Zap List', typ='list-single', name='zap',options=self.zaplist)])
           replypayload = [Node('actions',attrs={'execute':'next'},payload=[Node('next')]),form]
           reply.addChild(name='command',namespace=NS_COMMANDS,attrs={'node':request.getTagAttr('command','node'),'sessionid':session,'status':'executing'},payload=replypayload)
           self._owner.send(reply)
        else:
           self._owner.send(Error(request,ERR_FORBIDDEN))
        raise NodeProcessed

    def cmdSecondStage(self,conn,request):
        """Apply and save the config"""
        form = DataForm(node=request.getTag(name='command').getTag(name='x',namespace=NS_DATA))
        session = request.getTagAttr('command','sessionid')
        if self.sessions.has_key(session):
            if self.sessions[session]['jid'] == request.getFrom():
                fromstripped = request.getFrom().getStripped().encode('utf8')
                zap = form.getField('zap').getValue()
                if self.transport.userlist.has_key(fromstripped) and self.zapindexes.has_key(zap):
                    msid = request.getTo().getNode()
                    msidenc = msid.encode('utf-8')
                    msg = MS_msg_action_zap_prefix + str(self.zapindexes[zap])
                    msobj = self.transport.userlist[fromstripped]
                    msobj.msmsg_send_action(msidenc, msg)
                    reply = request.buildReply('result')
                    form = DataForm(typ='result',data=[DataField(value='Command completed.',typ='fixed')])
                    reply.addChild(name='command',namespace=NS_COMMANDS,attrs={'node':request.getTagAttr('command','node'),'sessionid':self.getSessionID(),'status':'completed'},payload=[form])
                    self._owner.send(reply)
                else:
                    self._owner.send(Error(request,ERR_BAD_REQUEST))
            else:
                self._owner.send(Error(request,ERR_BAD_REQUEST))
        else:
            self._owner.send(Error(request,ERR_BAD_REQUEST))
        raise NodeProcessed

    def cmdCancel(self,conn,request):
        session = request.getTagAttr('command','sessionid')
        if self.sessions.has_key(session):
            del self.sessions[session]
            reply = request.buildReply('result')
            reply.addChild(name='command',namespace=NS_COMMANDS,attrs={'node':request.getTagAttr('command','node'),'sessionid':session,'status':'canceled'})
            self._owner.send(reply)
        else:
            self._owner.send(Error(request,ERR_BAD_REQUEST))
        raise NodeProcessed
