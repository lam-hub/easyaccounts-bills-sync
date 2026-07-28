#!/usr/bin/env python3
"""
EasyAccounts 账单导入脚本
从微信账单 JSON 导入到 EasyAccounts 数据库
整合了所有修复逻辑：
- 亲属卡交易 → 转账分类
- 二娃相关 → 二娃账户
- 退款记录 → 退款收入分类
- 内部转账 → 内部转账分类
"""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# 数据库配置
DB_CONTAINER = "easy_accounts_db"
DB_USER = "root"
DB_PASSWORD = "easy_accounts"
DB_NAME = "yd_jz"

def run_sql(sql, show_output=False):
    """执行 SQL 命令"""
    cmd = [
        "docker", "compose", "exec", "-T", "db",
        "mysql", f"-u{DB_USER}", f"-p{DB_PASSWORD}", DB_NAME,
        "-e", sql
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, 
                          cwd="/home/share/easyaccounts-project")
    if show_output:
        return result.stdout
    return result

def get_max_id(table):
    """获取表中最大 ID"""
    sql = f"SELECT COALESCE(MAX(id), 0) as max_id FROM {table};"
    output = run_sql(sql, show_output=True)
    for line in output.strip().split('\n'):
        if line.isdigit():
            return int(line)
    return 0

def create_default_data():
    """创建默认账户和分类"""
    print("=== 创建默认数据 ===")
    
    # 检查是否已有basic账户
    sql = "SELECT COUNT(*) FROM account WHERE a_name = 'basic';"
    output = run_sql(sql, show_output=True)
    if '0' in output:
        sql = """
        INSERT INTO account (a_name, a_disable) 
        VALUES ('basic', 0);
        """
        run_sql(sql)
        print("✓ 创建账户: basic")
    else:
        print("✓ 账户 basic 已存在")
    
    # 检查是否已有二娃账户
    sql = "SELECT COUNT(*) FROM account WHERE a_name = '二娃';"
    output = run_sql(sql, show_output=True)
    if '0' in output:
        sql = """
        INSERT INTO account (a_name, a_disable) 
        VALUES ('二娃', 0);
        """
        run_sql(sql)
        print("✓ 创建账户: 二娃")
    else:
        print("✓ 账户 二娃 已存在")
    
    # 检查是否已有默认分类
    sql = "SELECT COUNT(*) FROM type WHERE t_name = '餐饮';"
    output = run_sql(sql, show_output=True)
    if '0' in output:
        # 创建默认分类
        categories = [
            ('餐饮', 0), ('交通', 0), ('购物', 0), ('娱乐', 0),
            ('医疗', 0), ('教育', 0), ('住房', 0), ('通讯', 0),
            ('转账', 0), ('红包', 0), ('其他', 0)
        ]
        
        for name, _ in categories:
            sql = f"INSERT INTO type (t_name, t_disable) VALUES ('{name}', 0);"
            run_sql(sql)
        print(f"✓ 创建 {len(categories)} 个默认分类")
    
    # 检查是否已有退款分类
    sql = "SELECT COUNT(*) FROM type WHERE t_name = '退款' AND action_id = 15;"
    output = run_sql(sql, show_output=True)
    if '0' in output:
        sql = """
        INSERT INTO type (t_name, action_id, t_disable) 
        VALUES ('退款', 15, 0);
        """
        run_sql(sql)
        print("✓ 创建分类: 退款(收入)")
    
    # 检查是否已有内部转账分类
    sql = "SELECT COUNT(*) FROM type WHERE t_name = '内部转账' AND action_id = 17;"
    output = run_sql(sql, show_output=True)
    if '0' in output:
        sql = """
        INSERT INTO type (t_name, action_id, t_disable) 
        VALUES ('内部转账', 17, 0);
        """
        run_sql(sql)
        print("✓ 创建分类: 内部转账")

def classify_transaction(bill, platform='wechat'):
    """
    根据平台和交易信息分类
    返回: (type_name, action_id, account_name)
    """
    if platform == 'alipay':
        return classify_alipay_transaction(bill)
    else:
        return classify_wechat_transaction(bill)


def classify_wechat_transaction(bill):
    """
    微信账单分类逻辑
    返回: (type_name, action_id, account_name)
    """
    trade_type = bill.get('交易类型', '')
    direction = bill.get('收/支', '')
    status = bill.get('当前状态', '')
    counterparty = bill.get('交易对方', '')
    product = bill.get('商品', '')
    desc = f"{product} {counterparty}".lower()
    
    # 1. 剔除中性交易（零钱充值、转入零钱通）
    if direction == '/':
        return ('内部转账', 17, 'basic')  # action_id=17 内部转账，不计入收支
    
    # 2. 根据收/支字段和交易类型判断
    if direction == '收入':
        # 收入类型：退款、转账、红包、群收款
        if '退款' in status or '退款' in trade_type:
            return ('退款', 15, 'basic')  # action_id=15 收入（包括二娃的退款）
        elif trade_type == '转账':
            # 只有二娃的转账属于内部转账
            if counterparty and '二娃' in counterparty:
                return ('内部转账', 17, '二娃')  # action_id=17 内部转账，不计入收支
            else:
                return ('转账', 15, 'basic')  # action_id=15 收入
        elif trade_type == '微信红包':
            return ('红包', 15, 'basic')  # action_id=15 收入
        elif trade_type == '群收款':
            return ('群收款', 15, 'basic')  # action_id=15 收入
        else:
            return ('其他收入', 15, 'basic')  # action_id=15 收入
    
    elif direction == '支出':
        # 支出类型：消费、亲属扣款、扫码付款
        if trade_type == '亲属卡交易':
            # 二娃的亲属卡交易正常统计为支出
            if counterparty and '二娃' in counterparty:
                return ('亲属卡交易', 16, '二娃')  # action_id=16 支出
            else:
                return ('亲属卡交易', 16, 'basic')  # action_id=16 支出
        elif '扫码' in trade_type or '消费' in trade_type:
            # 根据描述智能分类
            if any(kw in desc for kw in ['餐', '饭', '面', '粉', '包子', '奶茶', '咖啡', '外卖', '超市']):
                return ('餐饮', 16, 'basic')
            elif any(kw in desc for kw in ['宠物', '猫', '狗', '宠物店']):
                return ('宠物', 16, 'basic')
            elif any(kw in desc for kw in ['打车', '出租', '地铁', '公交', '加油', '停车']):
                return ('交通', 16, 'basic')
            elif any(kw in desc for kw in ['商场', '淘宝', '京东', '拼多多', '购物']):
                return ('购物', 16, 'basic')
            elif any(kw in desc for kw in ['电影', '游戏', 'ktv', '旅游']):
                return ('娱乐', 16, 'basic')
            elif any(kw in desc for kw in ['医院', '药', '诊所']):
                return ('医疗', 16, 'basic')
            elif any(kw in desc for kw in ['学费', '培训', '书']):
                return ('教育', 16, 'basic')
            elif any(kw in desc for kw in ['房租', '水电', '物业']):
                return ('住房', 16, 'basic')
            elif any(kw in desc for kw in ['话费', '流量', '宽带']):
                return ('通讯', 16, 'basic')
            elif any(kw in desc for kw in ['水费', '电费', '燃气', '煤气', '物业', '供水', '电力', '充电', '直饮水', '缴费', '公用事业']):
                return ('日用', 16, 'basic')
            else:
                return ('其他支出', 16, 'basic')
        else:
            return ('其他支出', 16, 'basic')
    
    else:
        # 默认分类
        return ('其他', 16, 'basic')


def classify_alipay_transaction(bill):
    """
    支付宝账单分类逻辑
    返回: (type_name, action_id, account_name)
    """
    trade_type = bill.get('交易类型', '')
    direction = bill.get('收/支', '')
    status = bill.get('当前状态', '')
    counterparty = bill.get('交易对方', '')
    product = bill.get('商品', '')
    desc = f"{product} {counterparty} {trade_type}".lower()
    
    # 1. 不计收支 → 内部转账（理财、还款等资金流转）
    if direction == '不计收支':
        return ('内部转账', 17, '支付宝')
    
    # 2. 收入
    if direction == '收入':
        if '退款' in status or '退款' in trade_type:
            return ('退款', 15, '支付宝')
        elif '转账' in trade_type:
            return ('转账', 15, '支付宝')
        elif '红包' in trade_type:
            return ('红包', 15, '支付宝')
        else:
            return ('其他收入', 15, '支付宝')
    
    # 3. 支出
    elif direction == '支出':
        # 根据交易类型分类
        if trade_type in ['宠物']:
            return ('宠物', 16, '支付宝')
        
        # 根据交易对方和商品关键词分类
        if any(kw in desc for kw in ['餐', '饭', '面', '粉', '包子', '奶茶', '咖啡', '外卖', '超市']):
            return ('餐饮', 16, '支付宝')
        elif any(kw in desc for kw in ['打车', '出租', '地铁', '公交', '加油', '停车', '滴滴', '高德']):
            return ('交通', 16, '支付宝')
        elif any(kw in desc for kw in ['商场', '淘宝', '京东', '拼多多', '购物', '天猫']):
            return ('购物', 16, '支付宝')
        elif any(kw in desc for kw in ['电影', '游戏', 'ktv', '旅游', '娱乐']):
            return ('娱乐', 16, '支付宝')
        elif any(kw in desc for kw in ['医院', '药', '诊所', '医疗']):
            return ('医疗', 16, '支付宝')
        elif any(kw in desc for kw in ['学费', '培训', '书', '教育']):
            return ('教育', 16, '支付宝')
        elif any(kw in desc for kw in ['房租', '水电', '物业', '住房']):
            return ('住房', 16, '支付宝')
        elif any(kw in desc for kw in ['话费', '流量', '宽带', '通讯']):
            return ('通讯', 16, '支付宝')
        elif any(kw in desc for kw in ['水费', '电费', '燃气', '煤气', '物业', '供水', '电力', '充电', '直饮水', '缴费', '公用事业']):
            return ('日用', 16, '支付宝')
        else:
            return ('其他支出', 16, '支付宝')
    
    else:
        # 默认分类
        return ('其他', 16, '支付宝')

def get_type_id(type_name):
    """获取分类 ID"""
    sql = f"SELECT id FROM type WHERE t_name = '{type_name}';"
    output = run_sql(sql, show_output=True)
    lines = output.strip().split('\n')
    for line in lines[1:]:  # 跳过表头
        if line.isdigit():
            return int(line)
    return 11  # 默认"其他"

def get_account_id(account_name):
    """获取账户 ID"""
    sql = f"SELECT id FROM account WHERE a_name = '{account_name}';"
    output = run_sql(sql, show_output=True)
    lines = output.strip().split('\n')
    for line in lines[1:]:
        if line.isdigit():
            return int(line)
    return 1

def get_action_id(direction, status):
    """获取动作 ID"""
    # 15=收入, 16=支出, 17=内部转账
    if '退款' in status:
        return 15  # 退款作为收入
    elif direction == '收入':
        return 15
    elif direction == '支出':
        return 16
    elif direction == '/':
        return 17  # 内部转账
    else:
        return 16  # 默认支出

def import_bills(json_file):
    """导入账单"""
    print(f"\n=== 导入账单: {json_file} ===")
    
    with open(json_file, 'r', encoding='utf-8') as f:
        bills = json.load(f)
    
    print(f"共 {len(bills)} 条记录")
    
    # 根据文件名判断平台
    filename = json_file.name.lower()
    if filename.startswith('alipay'):
        platform = 'alipay'
    elif filename.startswith('wechat'):
        platform = 'wechat'
    else:
        # 兜底：检查交易类型特征值
        if bills and bills[0].get('收/支') == '不计收支':
            platform = 'alipay'
        else:
            platform = 'wechat'
    
    print(f"检测到平台: {platform}")
    
    # 时间标准化：提取年月
    for bill in bills:
        trade_time = bill.get('交易时间', '')
        if trade_time:
            bill['月份'] = trade_time[:7]  # 格式：YYYY-MM
    
    # 退款正常统计为收入，不进行对冲
    
    # 预加载所有type和account的ID映射
    type_map = {}
    account_map = {}
    
    # 获取所有type
    sql = "SELECT id, t_name FROM type;"
    output = run_sql(sql, show_output=True)
    for line in output.strip().split('\n')[1:]:
        parts = line.split('\t')
        if len(parts) == 2 and parts[0].isdigit():
            type_map[parts[1]] = int(parts[0])
    
    # 获取所有account
    sql = "SELECT id, a_name FROM account;"
    output = run_sql(sql, show_output=True)
    for line in output.strip().split('\n')[1:]:
        parts = line.split('\t')
        if len(parts) == 2 and parts[0].isdigit():
            account_map[parts[1]] = int(parts[0])
    
    print(f"已加载 {len(type_map)} 个分类, {len(account_map)} 个账户")
    
    success_count = 0
    error_count = 0
    stats = {}
    
    # 批量处理，每批100条
    batch_size = 100
    total_batches = (len(bills) + batch_size - 1) // batch_size
    
    for batch_idx in range(total_batches):
        start_idx = batch_idx * batch_size
        end_idx = min((batch_idx + 1) * batch_size, len(bills))
        batch = bills[start_idx:end_idx]
        
        # 构建批量INSERT
        values_list = []
        for bill in batch:
            try:
                # 解析日期
                trade_time = bill.get('交易时间', '')
                if not trade_time:
                    continue
                
                date_str = trade_time.split(' ')[0]
                month_str = bill.get('月份', date_str[:7])
                
                # 分类（传入平台参数）
                type_name, action_id, account_name = classify_transaction(bill, platform)
                type_id = type_map.get(type_name, 114)  # 默认114=其他
                account_id = account_map.get(account_name, 47)  # 默认47=basic
                
                # 统计
                stats[type_name] = stats.get(type_name, 0) + 1
                
                # 金额（去掉千分位逗号）
                amount = bill.get('金额(元)', '0.00')
                if isinstance(amount, str):
                    amount = amount.replace(',', '')
                amount = float(amount)
                
                # 备注
                counterparty = bill.get('交易对方', '')
                product = bill.get('商品', '')
                note = f"{counterparty} {product}".strip()
                if not note or note == '/ /':
                    note = None
                
                # 转义单引号
                if note:
                    note = note.replace("'", "''")
                
                # 对冲标记：如果是对冲交易，设置 f_disable=1
                f_disable = 1 if bill.get('对冲') else 0
                
                # 构建VALUES
                note_sql = f"'{note}'" if note else "NULL"
                values_list.append(
                    f"('{date_str}', '{amount}', {type_id}, {action_id}, 0, {note_sql}, "
                    f"CURDATE(), {account_id}, NULL, 0, {f_disable}, '{platform}_import')"
                )
                success_count += 1
                
            except Exception as e:
                error_count += 1
                if error_count <= 5:
                    print(f"  ✗ 异常: {str(e)[:200]}")
        
        # 执行批量INSERT
        if values_list:
            sql = f"""
            INSERT INTO flow (f_date, money, type_id, action_id, exempt, note, 
                            f_create_date, account_id, account_to_id, collect, 
                            f_disable, from_source)
            VALUES {', '.join(values_list)};
            """
            
            result = run_sql(sql)
            if result.returncode != 0:
                print(f"  ✗ 批次 {batch_idx + 1} 错误: {result.stderr[:200]}")
        
        # 进度显示
        print(f"  进度: {end_idx}/{len(bills)}")
    
    print(f"\n=== 导入完成 ===")
    print(f"✓ 成功: {success_count}")
    print(f"✗ 失败: {error_count}")
    
    # 修复 account_to_id 为 NULL 的问题（Java实体类中是int基本类型，不能接受NULL）
    print("\n=== 修复 account_to_id NULL 值 ===")
    fix_sql = f"UPDATE flow SET account_to_id = 0 WHERE account_to_id IS NULL AND from_source = '{platform}_import';"
    run_sql(fix_sql, show_output=False)
    print("✓ 已修复 account_to_id NULL 值")
    
    print("\n=== 分类统计 ===")
    for type_name, count in sorted(stats.items(), key=lambda x: -x[1]):
        if count > 0:
            print(f"  {type_name}: {count}笔")

def main():
    # 检查 JSON 文件
    data_dir = Path("/home/share/easyaccounts-project/bills-sync/data")
    json_files = sorted(data_dir.glob("*.json"))
    
    if not json_files:
        print("错误: 未找到 JSON 文件")
        sys.exit(1)
    
    latest_json = json_files[-1]
    print(f"使用文件: {latest_json.name}")
    
    # 创建默认数据
    create_default_data()
    
    # 导入账单
    import_bills(latest_json)
    
    # 验证
    total = get_max_id("flow")
    print(f"\n数据库现有记录: {total}")

if __name__ == "__main__":
    main()
