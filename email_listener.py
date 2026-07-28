#!/usr/bin/env python3
"""邮件监听和账单下载"""

import imaplib
import email
import re
import requests
from email.header import decode_header
from datetime import datetime
from pathlib import Path
import yaml


class EmailListener:
    def __init__(self, config_path="config.yaml"):
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)
        
        self.mail = None
        self.data_dir = Path(self.config['storage']['data_dir'])
        self.data_dir.mkdir(exist_ok=True)
        self.processed_uid_file = Path(self.config['storage']['processed_uid_file'])
        self.processed_uids = self._load_processed_uids()
    
    def _load_processed_uids(self):
        if self.processed_uid_file.exists():
            with open(self.processed_uid_file, 'r') as f:
                return set(f.read().splitlines())
        return set()
    
    def _save_processed_uid(self, uid):
        with open(self.processed_uid_file, 'a') as f:
            f.write(f"{uid}\n")
    
    def connect(self):
        email_config = self.config['email']
        print(f"连接 {email_config['imap_server']}:{email_config['imap_port']} ...")
        self.mail = imaplib.IMAP4_SSL(
            email_config['imap_server'],
            email_config['imap_port']
        )
        print(f"登录 {email_config['address']} ...")
        self.mail.login(email_config['address'], email_config['password'])
        self.mail.select("INBOX")
        print("登录成功\n")
    
    def disconnect(self):
        if self.mail:
            self.mail.logout()
    
    def decode_mime_words(self, s):
        if not s:
            return ""
        decoded = []
        for content, charset in decode_header(s):
            if isinstance(content, bytes):
                decoded.append(content.decode(charset or 'utf-8', errors='ignore'))
            else:
                decoded.append(content)
        return ''.join(decoded)
    
    def check_wechat_bill(self, msg):
        from_addr = msg.get("From", "")
        subject = self.decode_mime_words(msg.get("Subject", ""))
        
        wechat_config = self.config['filters']['wechat']
        from_match = any(sender in from_addr for sender in wechat_config['from'])
        subject_match = any(keyword in subject for keyword in wechat_config['subject_keywords'])
        
        return from_match and subject_match
    
    def extract_download_link(self, msg):
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                try:
                    content = part.get_payload(decode=True)
                    if content:
                        html = content.decode('utf-8', errors='ignore')
                        links = re.findall(r'href=["\'](https?://[^"\']+)["\']', html)
                        for link in links:
                            if 'download' in link.lower() or 'billdownload' in link.lower():
                                return link
                except:
                    pass
            # 也检查纯文本中的链接
            if part.get_content_type() == "text/plain":
                try:
                    content = part.get_payload(decode=True)
                    if content:
                        text = content.decode('utf-8', errors='ignore')
                        links = re.findall(r'(https?://\S+)', text)
                        for link in links:
                            if 'download' in link.lower() or 'billdownload' in link.lower():
                                return link
                except:
                    pass
        return None
    
    def download_file(self, url, filename):
        print(f"  下载中...")
        try:
            response = requests.get(url, timeout=30, stream=True, allow_redirects=True)
            response.raise_for_status()
            
            content_type = response.headers.get('Content-Type', '')
            content_length = response.headers.get('Content-Length', 'unknown')
            print(f"  Content-Type: {content_type}, 大小: {content_length} bytes")
            
            filepath = self.data_dir / filename
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            file_size = filepath.stat().st_size
            print(f"  ✓ 已保存: {filepath} ({file_size} bytes)")
            return filepath
        except Exception as e:
            print(f"  ✗ 下载失败: {e}")
            return None
    
    def check_alipay_bill(self, msg):
        """检查是否为支付宝账单邮件"""
        from_addr = msg.get("From", "")
        subject = self.decode_mime_words(msg.get("Subject", ""))
        
        alipay_config = self.config['filters']['alipay']
        from_match = any(sender in from_addr for sender in alipay_config['from'])
        subject_match = any(keyword in subject for keyword in alipay_config['subject_keywords'])
        
        return from_match and subject_match
    
    def extract_attachment(self, msg):
        """从邮件中提取附件"""
        attachments = []
        for part in msg.walk():
            content_disposition = part.get("Content-Disposition", "")
            if "attachment" in content_disposition:
                filename = part.get_filename()
                if filename:
                    filename = self.decode_mime_words(filename)
                    content = part.get_payload(decode=True)
                    attachments.append({
                        'filename': filename,
                        'content': content
                    })
        return attachments
    
    def save_attachment(self, attachment, platform):
        """保存附件到本地"""
        filename = attachment['filename']
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_filename = f"{platform}_{timestamp}_{filename}"
        filepath = self.data_dir / save_filename
        
        try:
            with open(filepath, 'wb') as f:
                f.write(attachment['content'])
            print(f"  ✓ 已保存附件: {filepath} ({len(attachment['content'])} bytes)")
            return filepath
        except Exception as e:
            print(f"  ✗ 保存附件失败: {e}")
            return None
    
    def check_new_bills(self):
        print("检查新账单邮件...\n")
        
        # 搜索微信账单邮件
        print("搜索微信账单邮件...")
        wechat_config = self.config['filters']['wechat']
        wechat_sender = wechat_config['from'][0]
        status, wechat_messages = self.mail.search(None, f'FROM "{wechat_sender}"')
        
        wechat_bills = []
        if status == "OK":
            wechat_ids = wechat_messages[0].split()
            print(f"找到 {len(wechat_ids)} 封微信账单邮件\n")
            
            for email_id in wechat_ids:
                status, uid_data = self.mail.fetch(email_id, "(UID)")
                if status != "OK":
                    continue
                
                uid_str = str(uid_data[0])
                uid_match = re.search(r'UID (\d+)', uid_str)
                if not uid_match:
                    continue
                uid = uid_match.group(1)
                
                if uid in self.processed_uids:
                    print(f"  UID {uid} 已处理，跳过")
                    continue
                
                status, msg_data = self.mail.fetch(email_id, "(RFC822)")
                if status != "OK":
                    continue
                
                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)
                
                subject = self.decode_mime_words(msg.get("Subject", ""))
                print(f"处理: {subject}")
                
                download_link = self.extract_download_link(msg)
                if download_link:
                    print(f"  找到下载链接")
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"wechat_bill_{timestamp}.zip"
                    
                    filepath = self.download_file(download_link, filename)
                    if filepath:
                        wechat_bills.append({
                            'uid': uid,
                            'subject': subject,
                            'filepath': str(filepath),
                            'platform': 'wechat'
                        })
                        self._save_processed_uid(uid)
                else:
                    print(f"  ✗ 未找到下载链接")
                
                print()
        
        # 搜索支付宝账单邮件
        print("\n搜索支付宝账单邮件...")
        alipay_config = self.config['filters']['alipay']
        alipay_sender = alipay_config['from'][0]
        status, alipay_messages = self.mail.search(None, f'FROM "{alipay_sender}"')
        
        alipay_bills = []
        if status == "OK":
            alipay_ids = alipay_messages[0].split()
            print(f"找到 {len(alipay_ids)} 封支付宝账单邮件\n")
            
            for email_id in alipay_ids:
                status, uid_data = self.mail.fetch(email_id, "(UID)")
                if status != "OK":
                    continue
                
                uid_str = str(uid_data[0])
                uid_match = re.search(r'UID (\d+)', uid_str)
                if not uid_match:
                    continue
                uid = uid_match.group(1)
                
                if uid in self.processed_uids:
                    print(f"  UID {uid} 已处理，跳过")
                    continue
                
                status, msg_data = self.mail.fetch(email_id, "(RFC822)")
                if status != "OK":
                    continue
                
                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)
                
                subject = self.decode_mime_words(msg.get("Subject", ""))
                print(f"处理: {subject}")
                
                attachments = self.extract_attachment(msg)
                if attachments:
                    print(f"  找到 {len(attachments)} 个附件")
                    for attachment in attachments:
                        filepath = self.save_attachment(attachment, 'alipay')
                        if filepath:
                            alipay_bills.append({
                                'uid': uid,
                                'subject': subject,
                                'filepath': str(filepath),
                                'platform': 'alipay'
                            })
                    self._save_processed_uid(uid)
                else:
                    print(f"  ✗ 未找到附件")
                
                print()
        
        return wechat_bills + alipay_bills


if __name__ == "__main__":
    listener = EmailListener()
    try:
        listener.connect()
        bills = listener.check_new_bills()
        print(f"\n本次下载 {len(bills)} 个新账单")
    finally:
        listener.disconnect()
