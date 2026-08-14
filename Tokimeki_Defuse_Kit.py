import os
import struct
import unicodedata

# ==================== 常量定义 ====================
FILENAME = "tokimeki.sav"
OUT_FILENAME = "tokimeki_safe.sav"
SLOT_SIZE = 0xA770
SLOT_START_BASE = 0x60
NUM_SLOTS = 14
CHECKSUM_DWORD_OFFSET = 0x92864

# 日期偏移 (年/月/日)
DATE_YEAR_OFFSET  = 0x2F
DATE_MONTH_OFFSET = 0x30
DATE_DAY_OFFSET   = 0x31

# 主角核心属性内部相对偏移
STATS_INFO = {
    1: {"name": "体力 (HP)",    "offset": 0x08},
    2: {"name": "文科 (Lib)",   "offset": 0x0C},
    3: {"name": "理科 (Sci)",   "offset": 0x10},
    4: {"name": "艺术 (Art)",   "offset": 0x14},
    5: {"name": "运动 (PE)",    "offset": 0x18},
    6: {"name": "人缘 (Soc)",   "offset": 0x1C},
    7: {"name": "容姿 (App)",   "offset": 0x20},
    8: {"name": "毅力 (Will)",  "offset": 0x24},
    9: {"name": "压力 (Stress)","offset": 0x28}
}

# 女主角数据相对偏移基地址
GIRLS_BASE_OFFSET = {
    "friendship":  0x11AC,  # 友好度
    "heart_throb": 0x11CC,  # 心动度
    "heartbreak":  0x11EC   # 伤心度
}

# 角色列表 (严格按游戏内部 ID 排列)
GIRLS_LIST = [
    {"id": 0,  "name": "藤崎诗织"},
    {"id": 1,  "name": "如月未绪"},
    {"id": 2,  "name": "纽绪结奈"},
    {"id": 3,  "name": "片桐彩子"},
    {"id": 4,  "name": "虹野沙希"},
    {"id": 5,  "name": "古式由加利"},
    {"id": 6,  "name": "清川望"},
    {"id": 7,  "name": "镜魅罗"},
    {"id": 8,  "name": "朝日奈夕子"},
    {"id": 9,  "name": "美树原爱"},
    {"id": 10, "name": "早乙女优美"},
    {"id": 11, "name": "馆林见晴"},
    {"id": 12, "name": "伊集院丽"}
]

# ==================== 工具与底层函数 ====================
def get_disp_width(s):
    w = 0
    for c in s:
        if unicodedata.east_asian_width(c) in ('F', 'W', 'A'):
            w += 2
        else:
            w += 1
    return w

def pad_str(s, width):
    cur_len = get_disp_width(s)
    pad = max(0, width - cur_len)
    return s + (" " * pad)

def rol32(val, n):
    left_part = (val << n) & 0xFFFFFFFF
    right_part = val >> (32 - n)
    return left_part | right_part

def ror32(val, n):
    left_part = (val << (32 - n)) & 0xFFFFFFFF
    right_part = val >> n
    return left_part | right_part

def decrypt_dword(dword_val):
    return rol32(dword_val, 1)

def encrypt_dword(dword_val):
    return ror32(dword_val, 1)

def read_dword(data, offset):
    chunk = data[offset : offset + 4]
    return struct.unpack("<I", chunk)[0]

def write_dword(data, offset, val):
    data[offset : offset + 4] = struct.pack("<I", val)

def get_player_stat(data, slot_idx, stat_offset):
    abs_offset = SLOT_START_BASE + (slot_idx * SLOT_SIZE) + stat_offset
    enc_dword = read_dword(data, abs_offset)
    dec_dword = decrypt_dword(enc_dword)
    b1 = (dec_dword >> 8) & 0xFF
    b2_3 = (dec_dword >> 16) & 0xFFFF
    return b2_3 + (b1 / 256.0)

def read_decrypted_byte(data, slot_idx, rel_offset):
    abs_offset = SLOT_START_BASE + (slot_idx * SLOT_SIZE) + rel_offset
    dword_offset = abs_offset & ~3
    byte_index = abs_offset & 3
    enc_dword = read_dword(data, dword_offset)
    dec_dword = decrypt_dword(enc_dword)
    return (dec_dword >> (byte_index * 8)) & 0xFF

def modify_decrypted_byte(data, slot_idx, rel_offset, new_byte_val):
    """修改单个字节并返回该 DWORD 的字节校验和差值 (Delta)"""
    abs_offset = SLOT_START_BASE + (slot_idx * SLOT_SIZE) + rel_offset
    dword_offset = abs_offset & ~3
    byte_index = abs_offset & 3

    enc_dword = read_dword(data, dword_offset)
    dec_dword = decrypt_dword(enc_dword)

    b0 = dec_dword & 0xFF
    b1 = (dec_dword >> 8) & 0xFF
    b2 = (dec_dword >> 16) & 0xFF
    b3 = (dec_dword >> 24) & 0xFF
    old_sum = b0 + b1 + b2 + b3

    bytes_arr = [b0, b1, b2, b3]
    bytes_arr[byte_index] = new_byte_val & 0xFF

    new_sum = sum(bytes_arr)
    delta = new_sum - old_sum

    new_dec = (bytes_arr[3] << 24) | (bytes_arr[2] << 16)
    new_dec |= (bytes_arr[1] << 8) | bytes_arr[0]

    new_enc = encrypt_dword(new_dec)
    write_dword(data, dword_offset, new_enc)

    return delta

def update_global_checksum(data, total_delta):
    enc_dword = read_dword(data, CHECKSUM_DWORD_OFFSET)
    dec_dword = decrypt_dword(enc_dword)

    c0 = dec_dword & 0xFF
    c1 = (dec_dword >> 8) & 0xFF
    c2 = (dec_dword >> 16) & 0xFF
    c3 = (dec_dword >> 24) & 0xFF

    new_c2 = (c2 + total_delta) % 256

    new_dec = (c3 << 24) | (new_c2 << 16) | (c1 << 8) | c0
    new_enc = encrypt_dword(new_dec)
    write_dword(data, CHECKSUM_DWORD_OFFSET, new_enc)

def get_slot_date_str(data, slot_idx):
    """精确读取并格式化存档日期 (年/月/日)"""
    year_raw = read_decrypted_byte(data, slot_idx, DATE_YEAR_OFFSET)
    month    = read_decrypted_byte(data, slot_idx, DATE_MONTH_OFFSET)
    day      = read_decrypted_byte(data, slot_idx, DATE_DAY_OFFSET)

    full_year = 1900 + year_raw if year_raw >= 90 else 2000 + year_raw
    return f"{full_year}年{month:02d}月{day:02d}日"

def get_baseline_friendship(data, slot_idx):
    """获取常规女生(0~10)的最低基准友好度，默认下限为 14"""
    f_vals = []
    for g in GIRLS_LIST[:11]:
        f_offset = GIRLS_BASE_OFFSET["friendship"] + (g["id"] * 2)
        val = read_decrypted_byte(data, slot_idx, f_offset)
        if val > 0:
            f_vals.append(val)
    return min(f_vals) if f_vals else 14

# ==================== 界面展示 ====================
def display_slot_details(data, slot_idx):
    date_str = get_slot_date_str(data, slot_idx)
    print("\n" + "=" * 60)
    print(f" [查看存档] 槽位 Slot {slot_idx + 1:2d}  ({date_str})")
    print("=" * 60)

    print("【主角全部能力值】")
    items = []
    for idx in range(1, 10):
        info = STATS_INFO[idx]
        val = get_player_stat(data, slot_idx, info["offset"])
        item_text = pad_str(f"{info['name']}: {int(val):3d}", 18)
        items.append(item_text)
        if len(items) == 3:
            print("  " + "".join(items))
            items = []
    if items:
        print("  " + "".join(items))

    print("-" * 60)
    print("【女主角好感度与炸弹状态】")

    col_id = pad_str("ID", 4)
    col_name = pad_str("姓名", 14)
    col_f = pad_str("友好度", 10)
    col_l = pad_str("心动度", 10)
    col_h = pad_str("伤心度", 10)
    col_bomb = pad_str("炸弹状态", 10)
    print(" " + col_id + col_name + col_f + col_l + col_h + col_bomb)
    print("-" * 60)

    for girl in GIRLS_LIST:
        gid = girl["id"]
        name = girl["name"]

        f_offset = GIRLS_BASE_OFFSET["friendship"] + (gid * 2)
        l_offset = GIRLS_BASE_OFFSET["heart_throb"] + (gid * 2)
        h_offset = GIRLS_BASE_OFFSET["heartbreak"] + (gid * 2)

        f_val = read_decrypted_byte(data, slot_idx, f_offset)
        l_val = read_decrypted_byte(data, slot_idx, l_offset)
        h_val = read_decrypted_byte(data, slot_idx, h_offset)

        if h_val >= 60:
            bomb_status = "已经挂弹"
        elif h_val >= 55:
            bomb_status = "即将挂弹"
        else:
            bomb_status = "-"

        r_id = pad_str(str(gid), 4)
        r_name = pad_str(name, 14)
        r_f = pad_str(str(f_val), 10)
        r_l = pad_str(str(l_val), 10)
        r_h = pad_str(str(h_val), 10)
        r_bomb = pad_str(bomb_status, 10)

        print(" " + r_id + r_name + r_f + r_l + r_h + r_bomb)

    print("=" * 60)

# ==================== 交互与修改逻辑 ====================
def handle_operations(data, slot_idx):
    total_delta = 0
    modified = False

    while True:
        print("\n--- 心理维护与拆弹菜单 ---")
        print(" [0-12] 对指定女生单独拆弹   (伤心度清零)")
        print(" [R]    对指定女生心态重置   (友好基准/心动50/伤心0)")
        print(" [A]    一键全体拆弹         (所有女生伤心度清零)")
        print(" [S]    保存修改并输出新存档 tokimeki_safe.sav")
        print(" [Q]    退出当前槽位")

        sub_sel = input("请选择操作: ").strip().lower()

        if sub_sel == 'q':
            if modified:
                abandon = input("检测到未保存的修改，确认放弃吗？(Y/N): ").strip().lower()
                if abandon == 'y':
                    return
                continue
            return

        if sub_sel == 's':
            if not modified:
                print("[-] 尚未进行任何修改。")
                return
            break

        if sub_sel == 'a':
            confirm = input("确认要将所有女生的伤心度清零吗？(Y/N): ").strip().lower()
            if confirm == 'y':
                for girl in GIRLS_LIST:
                    gid = girl["id"]
                    h_offset = GIRLS_BASE_OFFSET["heartbreak"] + (gid * 2)
                    cur_h = read_decrypted_byte(data, slot_idx, h_offset)
                    if cur_h > 0:
                        delta = modify_decrypted_byte(data, slot_idx, h_offset, 0)
                        total_delta += delta
                modified = True
                print("[+] 全体拆弹操作完成！")
                display_slot_details(data, slot_idx)
            continue

        if sub_sel == 'r':
            try:
                target_str = input("请输入要重置的女生 ID (0-12): ").strip()
                t_id = int(target_str)
                if t_id < 0 or t_id >= len(GIRLS_LIST):
                    print("[-] 无效的女生 ID。")
                    continue

                target_girl = GIRLS_LIST[t_id]
                base_f = get_baseline_friendship(data, slot_idx)

                f_off = GIRLS_BASE_OFFSET["friendship"] + (t_id * 2)
                l_off = GIRLS_BASE_OFFSET["heart_throb"] + (t_id * 2)
                h_off = GIRLS_BASE_OFFSET["heartbreak"] + (t_id * 2)

                d_f = modify_decrypted_byte(data, slot_idx, f_off, base_f)
                d_l = modify_decrypted_byte(data, slot_idx, l_off, 50)
                d_h = modify_decrypted_byte(data, slot_idx, h_off, 0)

                total_delta += (d_f + d_l + d_h)
                modified = True
                print(f"[+] 已重置【{target_girl['name']}】：友好度->{base_f}, 心动度->50, 伤心度->0")
                display_slot_details(data, slot_idx)

            except ValueError:
                print("[-] 输入错误，请输入有效的数字 ID。")
            continue

        try:
            target_id = int(sub_sel)
            if target_id < 0 or target_id >= len(GIRLS_LIST):
                print("[-] 无效的女生 ID。")
                continue

            target_girl = GIRLS_LIST[target_id]
            h_offset = GIRLS_BASE_OFFSET["heartbreak"] + (target_id * 2)
            cur_h = read_decrypted_byte(data, slot_idx, h_offset)

            if cur_h == 0:
                print(f"[-] 【{target_girl['name']}】当前伤心度已为 0。")
                continue

            delta = modify_decrypted_byte(data, slot_idx, h_offset, 0)
            total_delta += delta
            modified = True
            print(f"[+] 已拆弹：【{target_girl['name']}】伤心度从 {cur_h} 调整为 0。")
            display_slot_details(data, slot_idx)

        except ValueError:
            print("[-] 输入错误，请输入数字 ID、r、a、s 或 q。")

    # 输出保存文件
    confirm_save = input(f"\n确认生成安全存档 '{OUT_FILENAME}'？(Y/N): ").strip().lower()
    if confirm_save != 'y':
        print("[-] 已取消保存。")
        return

    update_global_checksum(data, total_delta)

    try:
        with open(OUT_FILENAME, "wb") as f:
            f.write(data)
        print(f"\n[+] 保存成功！新存档已输出至：{OUT_FILENAME}")
        print(f"[*] 重命名覆盖原 {FILENAME} 即可载入。")
    except Exception as e:
        print(f"[-] 写入文件失败：{e}")

# ==================== 主入口 ====================
def main():
    print("=" * 50)
    print(" 《心跳回忆》存档数据维护与拆弹工具")
    print("=" * 50)

    if not os.path.exists(FILENAME):
        print(f"[-] 错误：未找到 {FILENAME} 文件！")
        return

    with open(FILENAME, "rb") as f:
        data = bytearray(f.read())

    occupied_slots = []
    for i in range(NUM_SLOTS):
        hp = get_player_stat(data, i, STATS_INFO[1]["offset"])
        if hp > 0:
            occupied_slots.append(i)

    if not occupied_slots:
        print("[-] 提示：未检测到已占用的存档槽位。")
        return

    print("\n[+] 检测到以下已占用的存档槽位：")
    for display_idx, slot_idx in enumerate(occupied_slots, 1):
        date_str = get_slot_date_str(data, slot_idx)
        print(f"  {display_idx:2d}. Slot {slot_idx + 1:2d}  ({date_str})")

    while True:
        try:
            choice = input(f"\n请选择槽位 (1-{len(occupied_slots)}, 输入 Q 退出): ").strip()
            if choice.lower() == 'q':
                break

            sel = int(choice)
            if sel < 1 or sel > len(occupied_slots):
                print("[-] 序号超出范围。")
                continue

            target_slot_idx = occupied_slots[sel - 1]
            display_slot_details(data, target_slot_idx)
            handle_operations(data, target_slot_idx)

        except ValueError:
            print("[-] 输入无效，请输入数字。")

if __name__ == "__main__":
    main()
