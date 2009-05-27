import types
from xmpp.simplexml import Node

try:
    import xml.etree.cElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET

msim_emoticons = (
    ( "bigsmile", ":D" ),
    ( "bigsmile", ":-D" ),
    ( "devil", "}:)" ),
    ( "frazzled", ":Z" ),
    ( "geek", "B)" ),
    ( "googles", "%)" ),
    ( "growl", ":E" ),
    ( "laugh", ":))" ), # Must be before ':)'
    ( "happy", ":)" ),
    ( "happy", ":-)" ),
    ( "happi", ":)" ),
    ( "heart", ":X" ),
    ( "mohawk", "-:" ),
    ( "mad", "X(" ),
    ( "messed", "X)" ),
    ( "nerd", "Q)" ),
    ( "oops", ":G" ),
    ( "pirate", "P)" ),
    ( "scared", ":O" ),
    ( "sidefrown", ":(" ),
    ( "sinister", ":B" ),
    ( "smirk", ":," ),
    ( "straight", ":|" ),
    ( "tongue", ":P" ),
    ( "tongue", ":p" ),
    ( "tongy", ":P" ),
    ( "upset", "B|" ),
    ( "wink", ";-)" ),
    ( "wink", ";)" ),
    ( "winc", ";)" ),
    ( "worried", ":[" ),
    ( "kiss", ":x" ))

# Start Region - MySpace markup to Text and XHTML

def myspace_str_to_text_xhtml(text):
    if text:
        text = unicode(text,'utf-8','replace')
    else:
        text = ''
    return text

MSIM_TEXT_BOLD      = 1
MSIM_TEXT_ITALIC    = 2
MSIM_TEXT_UNDERLINE = 4

def myspace_f_to_text_xhtml(node, xnode):
    f = node.attrib.has_key('f') and node.attrib['f']
    h = node.attrib.has_key('h') and int(node.attrib['h'])
    s = node.attrib.has_key('s') and int(node.attrib['s'])
    text = ''
    style = ''
    if f:
        style += 'font-family: \'%s\';' % f
    if h:
        style += 'font-size: %dpx;' % h
    if s:
        if s & MSIM_TEXT_BOLD:
            text += '*'
            style += 'font-weight: bold;'
        if s & MSIM_TEXT_ITALIC:
            text += '/'
            style += 'font-style: italic;'
        if s & MSIM_TEXT_UNDERLINE:
            text += '_'
            style += 'text-decoration: underline'
    return text,text[::-1], xnode.addChild('span', attrs={'style':style})

def myspace_a_to_text_xhtml(node, xnode):
    return h,'',xnode.addChild('a', attrs={'href':node.attrib['h']})

def myspace_p_to_text_xhtml(node, xnode):
    return '','',xnode.addChild('p')

def myspace_c_to_text_xhtml(node, xnode):
    return '','',xnode.addChild('span', attrs={'style':"color: %s" % node.attrib['v']})

def myspace_b_to_text_xhtml(node, xnode):
    return '','',xnode.addChild('span', attrs={'style':"background-color: %s" % node.attrib['v']})

def myspace_i_to_text_xhtml(node, xnode):
    n = node.attrib['n']
    emot = '**' + n + '**'
    for smiley in msim_emoticons:
        if smiley[0] == n:
            emot = smiley[1]
            break
    xnode.addData(emot)
    return emot,'',None

myspace_x_to_text_xhtml = {
    'f':myspace_f_to_text_xhtml,
    'a':myspace_a_to_text_xhtml,
    'p':myspace_p_to_text_xhtml,
    'c':myspace_c_to_text_xhtml,
    'b':myspace_b_to_text_xhtml,
    'i':myspace_i_to_text_xhtml}

def myspace_to_text_xhtml(node, xnode):
    if type(node) in types.StringTypes:
        text = myspace_str_to_text_xhtml(node)
        xnode.addData(text)
        return text, '', xnode
    elif myspace_x_to_text_xhtml.has_key(node.tag):
        start, end, subnode = myspace_x_to_text_xhtml[node.tag](node, xnode)
        text = myspace_str_to_text_xhtml(node.text)
        if text: subnode.addData(text)
        return start + text, end, subnode
    else:
        text = myspace_str_to_text_xhtml(node.text)
        xnode.addData(text)
        return text, '', xnode

def convert_node_myspace_to_text_xhtml(node, xnode):
    text, end, subnode = myspace_to_text_xhtml(node, xnode)
    for child in node.getchildren():
        text += convert_node_myspace_to_text_xhtml(child, subnode)
    text += end
    if node.tail:
        text += myspace_to_text_xhtml(node.tail, xnode)[0]
    return text

def mshtmlformat(text):
    """Converts a MySpace formatted message into a (text,html) tuple"""
    html = Node('html')
    html.setNamespace('http://jabber.org/protocol/xhtml-im')
    xhtml = html.addChild('body',namespace='http://www.w3.org/1999/xhtml')
    tree = ET.XML('<body>' + text + '</body>')
    text = convert_node_myspace_to_text_xhtml(tree, xhtml)
    return text,html

# End Region - MySpace markup to Text and XHTML

# Start Region - Text and XHTML to MySpace markup

def xhtml_to_myspace(node):
    if type(node) in types.StringTypes:
        return node
    else:
        return node.text

def convert_node_xhtml_to_myspace(msnode):
    final = ''
    text = xhtml_to_myspace(msnode)
    final += text
    for child in msnode.getchildren():
        final += convert_node_xhtml_to_myspace(child)
    if msnode.tail: final += xhtml_to_myspace(msnode.tail)
    return final

def convert_smileys_to_markup(text):
    for emoti in msim_emoticons:
        text = text.replace(emoti[1], '<i n=\"%s\"/>' % emoti[0])
    return text

def msnativeformat(text,xhtml):
    """Converts an html or text message into MySpace format"""
    if xhtml:
        tree = ET.XML('<body>' + xhtml + '</body>')
        str = convert_node_xhtml_to_myspace(tree).encode('utf-8')
    else:
        str = text.replace('<','&lt;').replace('>','&gt;').encode('utf-8')
    return convert_smileys_to_markup(str)

# End Region - Text and XHTML to MySpace markup

if __name__ == '__main__':
    text = 'Hello <f s=\'1\' h=\'16\'>bold</f> world, <i n="happy"/>'
    text = "<p><f f='Arial' h='96' s='1'><c v='black'><b v='rgba(255, 255, 255, 0)'>9</b></c></f></p>"
    text,xhtml = mshtmlformat(text)
    print 'text :',text
    print 'xhtml:',xhtml
    markup = msnativeformat('Hello *text* world, :-)',None)
    print 'text :',markup
    markup = msnativeformat(None,'Hello <span style="text-weight: bold">html</span> world, :-)')
    print 'xhtml:',markup
