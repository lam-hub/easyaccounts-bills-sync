#!/usr/bin/env python3
"""
微信/支付宝账单自动同步工具
流程：邮件下载 → 解压 → 解析 → 导入EasyAccounts
"""

import os
import sys
import argparse
import yaml
import zipfile
import shutil
from pathlib import Path
from datetime import datetime

from email_listener import EmailListener
from csv_parser import parse_wechat_bill, parse_alipay_bill, summary
from easyaccounts_import import import_bills, create_default_data


def load_config():
    """加载配置文件"""
    config_path = Path(__file__).parent / 'config.yaml'
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def extract_zip(zip_path, password):
    """解压zip文件，支持xlsx和csv"""
    extract_dir = zip_path.parent / zip_path.stem
    extract_dir.mkdir(exist_ok=True)
    
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir, pwd=password.encode())
        
        # 优先找xlsx，其次找csv
        xlsx_files = list(extract_dir.glob('*.xlsx'))
        if xlsx_files:
            return xlsx_files[0]
        
        csv_files = list(extract_dir.glob('*.csv'))
        if csv_files:
            return csv_files[0]
        
        print(f"✗ 解压目录中没有找到xlsx或csv文件: {extract_dir}")
        return None
    except Exception as e:
        print(f"✗ 解压失败: {e}")
        return None


def process_new_bills(config, wechat_password=None, alipay_password=None):
    """处理新账单"""
    data_dir = Path(config['storage']['data_dir'])
    data_dir.mkdir(exist_ok=True)
    
    # 1. 下载新账单
    print("=" * 60)
    print("步骤1: 检查并下载新账单")
    print("=" * 60)
    
    listener = EmailListener()
    try:
        listener.connect()
        new_bills = listener.check_new_bills()
    finally:
        listener.disconnect()
    
    if not new_bills:
        print("\n没有新的账单需要处理")
        return
    
    print(f"\n✓ 下载了 {len(new_bills)} 个新账单\n")
    
    # 按平台分组
    wechat_bills = [b for b in new_bills if b['platform'] == 'wechat']
    alipay_bills = [b for b in new_bills if b['platform'] == 'alipay']
    
    all_records = []
    
    # 2. 处理微信账单
    if wechat_bills:
        print("=" * 60)
        print(f"处理微信账单 ({len(wechat_bills)} 个)")
        print("=" * 60)
        
        if wechat_password is None:
            password = input("请输入微信账单解压密码: ").strip()
        else:
            password = wechat_password
            print(f"使用命令行提供的微信密码")
        
        wechat_account_id = config['accounts']['wechat']
        
        for bill in wechat_bills:
            zip_path = Path(bill['filepath'])
            print(f"\n解压: {zip_path.name}")
            
            xlsx_path = extract_zip(zip_path, password)
            if not xlsx_path:
                continue
            
            print(f"✓ 解压成功: {xlsx_path.name}")
            
            try:
                records = parse_wechat_bill(xlsx_path)
                print(f"✓ 解析了 {len(records)} 条记录")
                
                # 为每条记录添加账户ID
                for record in records:
                    record['account_id'] = wechat_account_id
                
                stats = summary(records)
                print(f"  收入: {stats['income_count']}笔, {stats['income_total']:.2f}元")
                print(f"  支出: {stats['expense_count']}笔, {stats['expense_total']:.2f}元")
                
                all_records.extend(records)
                
                # 保存解析结果
                output_file = data_dir / f"{zip_path.stem}_parsed.json"
                import json
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(records, f, ensure_ascii=False, indent=2)
                print(f"✓ 已保存: {output_file}")
                
            except Exception as e:
                print(f"✗ 解析失败: {e}")
                continue
    
    # 3. 处理支付宝账单
    if alipay_bills:
        print("\n" + "=" * 60)
        print(f"处理支付宝账单 ({len(alipay_bills)} 个)")
        print("=" * 60)
        
        if alipay_password is None:
            password = input("请输入支付宝账单解压密码: ").strip()
        else:
            password = alipay_password
            print(f"使用命令行提供的支付宝密码")
        
        alipay_account_id = config['accounts']['alipay']
        
        for bill in alipay_bills:
            zip_path = Path(bill['filepath'])
            print(f"\n解压: {zip_path.name}")
            
            # 支付宝附件可能是zip或csv
            if zip_path.suffix.lower() == '.zip':
                csv_path = extract_zip(zip_path, password)
                if not csv_path:
                    continue
            else:
                csv_path = zip_path
            
            print(f"✓ 解压成功: {csv_path.name}")
            
            try:
                records = parse_alipay_bill(csv_path)
                print(f"✓ 解析了 {len(records)} 条记录")
                
                # 为每条记录添加账户ID
                for record in records:
                    record['account_id'] = alipay_account_id
                
                stats = summary(records)
                print(f"  收入: {stats['income_count']}笔, {stats['income_total']:.2f}元")
                print(f"  支出: {stats['expense_count']}笔, {stats['expense_total']:.2f}元")
                
                all_records.extend(records)
                
                # 保存解析结果
                output_file = data_dir / f"{zip_path.stem}_parsed.json"
                import json
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(records, f, ensure_ascii=False, indent=2)
                print(f"✓ 已保存: {output_file}")
                
            except Exception as e:
                print(f"✗ 解析失败: {e}")
                continue
    
    # 4. 导入EasyAccounts
    if all_records:
        print("\n" + "=" * 60)
        print("步骤4: 导入EasyAccounts")
        print("=" * 60)
        print(f"共 {len(all_records)} 条记录待导入")
        
        # 创建默认数据
        create_default_data()
        
        # 导入微信账单
        if wechat_bills:
            wechat_json_files = list(data_dir.glob("wechat_bill_*_parsed.json"))
            if wechat_json_files:
                latest_wechat = max(wechat_json_files, key=lambda p: p.stat().st_mtime)
                print(f"\n导入微信账单: {latest_wechat.name}")
                import_bills(latest_wechat)
        
        # 导入支付宝账单
        if alipay_bills:
            alipay_json_files = list(data_dir.glob("alipay_*_parsed.json"))
            if alipay_json_files:
                latest_alipay = max(alipay_json_files, key=lambda p: p.stat().st_mtime)
                print(f"\n导入支付宝账单: {latest_alipay.name}")
                import_bills(latest_alipay)
        
        print("\n✓ 导入完成")


def reimport_all(config):
    """重新导入所有JSON账单"""
    data_dir = Path(config['storage']['data_dir'])
    
    print("=" * 60)
    print("重新导入所有账单")
    print("=" * 60)
    
    # 创建默认数据
    create_default_data()
    
    # 导入微信账单
    wechat_json_files = sorted(data_dir.glob("wechat_bill_*_parsed.json"))
    if wechat_json_files:
        latest_wechat = wechat_json_files[-1]
        print(f"\n导入微信账单: {latest_wechat.name}")
        import_bills(latest_wechat)
    
    # 导入支付宝账单
    alipay_json_files = sorted(data_dir.glob("alipay_*_parsed.json"))
    if alipay_json_files:
        latest_alipay = alipay_json_files[-1]
        print(f"\n导入支付宝账单: {latest_alipay.name}")
        import_bills(latest_alipay)
    
    print("\n✓ 重新导入完成")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='微信/支付宝账单自动同步工具')
    parser.add_argument('--wechat-password', help='微信账单解压密码')
    parser.add_argument('--alipay-password', help='支付宝账单解压密码')
    parser.add_argument('--reimport', action='store_true', help='重新导入所有JSON账单')
    
    args = parser.parse_args()
    
    config = load_config()
    
    print("=" * 60)
    print("微信/支付宝账单自动同步工具")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    print()
    
    try:
        if args.reimport:
            reimport_all(config)
        else:
            process_new_bills(
                config,
                wechat_password=args.wechat_password,
                alipay_password=args.alipay_password
            )
        print("\n✓ 同步完成")
    except KeyboardInterrupt:
        print("\n\n用户中断")
        sys.exit(0)
    except Exception as e:
        print(f"\n✗ 同步失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
