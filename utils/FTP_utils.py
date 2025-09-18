import pysftp

'''
with pysftp.Connection('127.0.0.1', username='tester', password='password', port=222) as sftp:
    with sftp.cd('public'):             # temporarily chdir to public
        sftp.put('FTPTEST.txt')  # upload file to public/ on remote
        sftp.get('remote_file')         # get a remote file
'''

import paramiko 
def sftp_put(): 
    #文件路徑 
    local_file =r'I:\Downloads\RebexTinySftpServer-Binaries-Latest\abc.txt' 
    remote_file ='flash:/123.txt' 
    t = paramiko.Transport('127.0.0.1', 2222) 
    t.connect(username='tester', password='password') 
    sftp = paramiko.SFTPClient.from_transport(t) 
    sftp.put(local_file,remote_file) 
    t.close() 
def sftp_get(): 
    local_path = r'D:\test\vrpcfg.zip' 
    remote_path = 'flash:/vrpcfg.zip' 
    t = paramiko.Transport('192.168.0.200', 22) 
    t.connect(username='admin', password='Admin@123') 
    #
    sftp = paramiko.SFTPClient.from_transport(t)
    sftp.get(remote_path, local_path) 
    t.close()

if __name__ == '__main__':
    sftp_put()
    sftp_get()
   
    
    
#!/usr/bin/env python #coding:utf-8 
#歡迎關注微信公眾號：點滴技術 
#這裡有靠譜的、有價值的、共成長的，專屬於網絡攻城獅
import paramiko, time 
from paramiko.ssh_exception import NoValidConnectionsError,AuthenticationException
def ssh_client(host, user, pwd, cmds, verbose=True): 
    # 私鑰文件的存放路徑 
    # 
    private = paramiko.RSAKey.from_private_key_file(r'C:\Users\singvis\Documents\Identity') 
    # 創建一個實例化 
    ssh = paramiko.SSHClient() 
    # 加載系統SSH密鑰 
    ssh.load_system_host_keys() 
    # 自動添加策略，保存伺服器的主機名和密鑰信息，如果不添加，那麼不在本地knows_hosts文件中記錄的主機將無法連接，默認拒接
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy()) 
    # 連接設備 
    try:
        ssh.connect(hostname=host, username=user, timeout=5, compress=True, password=pwd
                    #pkey=private, #可以採用密鑰連接 ) print("正在連接主機{}.....".format(host)) except NoValidConnectionsError: print('連接出現了問題') except AuthenticationException: print('用戶名或密碼錯誤') except Exception as e: print('其他錯誤問題{}'.format(e)) finally: #激活交互式shell chan = ssh.invoke_shell() time.sleep(1) for cmd in cmds: chan.send(cmd.encode()) #一定要有回車'Enter'這個動作 chan.send(b'\n') time.sleep(2) r = chan.recv(40960).decode() if verbose: print(r) chan.close() ssh.close() def sftp_get(ip, user, pwd, local_file,remote_file, port=22): try: t = paramiko.Transport(ip, port) t.connect(username=user, password=pwd) sftp = paramiko.SFTPClient.from_transport(t) sftp.get(remote_file, local_file) t.close() except Exception as e: print(e) def sftp_put(ip, user, pwd, local_file, remote_file, port=22): try: t = paramiko.Transport(ip, port) t.connect(username=user, password=pwd) sftp = paramiko.SFTPClient.from_transport(t) sftp.put(local_file, remote_file) t.close() except Exception as e: print(e) if __name__ == '__main__': ''' 不要運行的，請注釋掉，前面加'#'符號 ''' ip = '192.168.0.101' user= 'admin' pwd= 'Admin@123' # local_file = r'D:\test\123.txt' # remote_file = 'flash:/vrpcfg.zip' # sftp_get(ip='192.168.0.200', user=user, pwd=pwd, remote_file=remote_file, local_file=r'D:\test\vrpcfg.zip') # sftp_put(ip='192.168.0.200', user=user, pwd=pwd, local_file=local_file, remote_file='flash:/123.txt') cmds = ['terminal length 0', 'show version', 'show ip int br','show ip route'] # cmds = ['disp ip int br','disp device','disp clock'] ssh_client(ip, user, pwd, cmds)

#原文網址：https://kknews.cc/code/gpxalvl.html
    

'''    
ssh = paramiko.SSHClient()
ssh.load_host_keys(os.path.expanduser(os.path.join("~", ".ssh", "known_hosts")))
ssh.connect(server, username=username, pkey=mykey)
sftp = ssh.open_sftp()

# Updated code below:
filesInRemoteArtifacts = sftp.listdir(path=remoteArtifactPath)
for file in filesInRemoteArtifacts:
    sftp.remove(remoteArtifactPath+file)

# Close to end
sftp.close()
ssh.close()
'''

'''
import posixpath
from stat import S_ISDIR
def rmtree(sftp, remotepath, level=0):
    for f in sftp.listdir_attr(remotepath):
        rpath = posixpath.join(remotepath, f.filename)
        if stat.S_ISDIR(f.st_mode):
            rmtree(sftp, rpath, level=(level + 1))
        else:
            rpath = posixpath.join(remotepath, f.filename)
            print('removing %s%s' % ('    ' * level, rpath))
            sftp.remove(rpath)
    print('removing %s%s' % ('    ' * level, remotepath))
    sftp.rmdir(remotepath)

ssh = paramiko.SSHClient()
ssh.load_host_keys(os.path.expanduser(os.path.join("~", ".ssh", "known_hosts")))
ssh.connect(server, username=username, pkey=mykey)
sftp = ssh.open_sftp()
rmtree(sftp, remoteArtifactPath)

# Close to end
stfp.close()
ssh.close()
'''