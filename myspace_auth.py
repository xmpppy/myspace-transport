import base64, hashlib, socket
from Crypto.Cipher import ARC4

def process_auth(username, password, seed, ip_list):
    # response = encrypt(key=hash(hash(pw) + nc2), data=nc1+username+IP_list)
    pw = password[:10].lower().encode('utf-16-le')
    nc1,nc2 = seed[:0x20],seed[0x20:]
    pwhash = hashlib.sha1(pw).digest()
    key = hashlib.sha1(pwhash + nc2).digest()
    rc4 = ARC4.new(key[:0x10])
    ip_list = chr(len(ip_list)) + ''.join([socket.inet_aton(x) for x in ip_list])
    data = nc1 + username + '\x00\x00\x00\x00' + ip_list
    return rc4.encrypt(data)

if __name__ == '__main__':

    def test(user, pwd, chal, responsetrue):
        print ''
        print "user: '%s'"% user
        print "pass: '%s'"% pwd
        print "chal: '%s'"% chal

        responsecalc = process_auth(user, pwd, chal, ['127.0.0.1'])

        checklen = 60
        # Only check the begining of the string, because the IP addresses will make the end differ
        # If the password is wrong, then it will be extremely different because of the encryption
        status = 'FAILED'
        if responsetrue[:checklen] == responsecalc[:checklen]: status = 'PASSED'

        print "response: '%s' (%s)"%( responsecalc, status)

    test_cases = (
        ('username' , 'password', 'NAn+pdqJh+G2NGkzrHbDmnbVpd1WxasA3VQyNoNt9GVKAOj1/A/nW7RuBxlO6b8Kk+vV8fcqGyhNxB4BdJ066w==', '0hH1zf4rG/Ol0zmmuyiXFEUvr6ESjWw3seIM+VAX47frSsK2eQYFyIK7TSsFm7abYQ=='),
        ('myuser'   , 'mypass'  , 'NAn+pdqJh+G2NGkzrHbDmnbVpd1WxasA3VQyNoNt9GVKAOj1/A/nW7RuBxlO6b8Kk+vV8fcqGyhNxB4BdJ066w==', '6qCvZ7oSVCGrt4NrXVfQZsDvduUQnDNZsKAY+FyIPY15lk12aMCX+B1QStRnBi4='),
        ('username' , 'password', '6BwwT6qLVrgWhe9vzFq9eyQdjrvPqJyqvE8+m/Vqw64iol9hJo408L78i9yYqs1CmE/bc5k/WfDteMjxyNa1eg=='  , 'xgGa4PtmD6ksFhUfnRCMqeXYFd9tIYFup46rfevUtxIzULrUmQLf+SMo1dozAihCTw=='),
        ('myuser'   , 'mypass'  , '6BwwT6qLVrgWhe9vzFq9eyQdjrvPqJyqvE8+m/Vqw64iol9hJo408L78i9yYqs1CmE/bc5k/WfDteMjxyNa1eg=='  , 'X1/icjyYwsiaVc9EmalHylzHpC/kLama+XcIEOOlIbn01ihGBJpx2hFPKkkqoWk='),
    )

    for user, pwd, chal, responsetrue in test_cases:
        test(user, pwd, chal, responsetrue)
