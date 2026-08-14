import os
import struct

# 常量定义
FILENAME = "tokimeki.sav"
OUT_FILENAME = "tokimeki_mod.sav"
SLOT_SIZE = 0xA770
SLOT_START_BASE = 0x60
NUM_SLOTS = 14
CHECKSUM_DWORD_OFFSET = 0x92864

# 属性内部偏移对应表
STATS_INFO = {
    1: {"name": "体力 (HP)",   "offset": 0x08},
    2: {"name": "文科 (Lib)",  "offset": 0x0C},
    3: {"name": "理科 (Sci)",  "offset": 0x10},
    4: {"name": "艺术 (Art)",  "offset": 0x14},
    5: {"name": "运动 (PE)",   "offset": 0x18},
    6: {"name": "人缘 (Soc)",  "offset": 0x1C},
    7: {"name": "容姿 (App)",  "offset": 0x20},
    8: {"name": "毅力 (Will)", "offset": 0x24},
    9: {"name": "压力 (Stress)","offset": 0x28}
}

def rol32(val, n):
    return ((val << n) & 0xFFFFFFFF) | (val >> (32 - n))

def ror32(val, n):
    return (val >> n) | ((val << (32 - n)) & 0xFFFFFFFF)

def decrypt_dword(dword_val):
    return rol32(dword_val, 1)

def encrypt_dword(dword_val):
    return ror32(dword_val, 1)

def read_dword(data, offset):
    return struct.unpack("<I", data[offset:offset+4])[0]

def write_dword(data, offset, val):
    data[offset:offset+4] = struct.pack("<I", val)

def get_stat_value(data, slot_idx, stat_offset):
    abs_offset = SLOT_START_BASE + slot_idx * SLOT_SIZE + stat_offset
    enc_dword = read_dword(data, abs_offset)
    dec_dword = decrypt_dword(enc_dword)
    b1 = (dec_dword >> 8) & 0xFF
    b2_3 = (dec_dword >> 16) & 0xFFFF
    return b2_3 + (b1 / 256.0)

# 物理拆分大数修改函数
def modify_stat_value(data, slot_idx, stat_offset, new_val):
    abs_offset = SLOT_START_BASE + slot_idx * SLOT_SIZE + stat_offset
    enc_dword = read_dword(data, abs_offset)
    dec_dword = decrypt_dword(enc_dword)
    
    old_b0 = dec_dword & 0xFF
    old_b1 = (dec_dword >> 8) & 0xFF
    old_b2 = (dec_dword >> 16) & 0xFF
    old_b3 = (dec_dword >> 24) & 0xFF
    old_sum = old_b0 + old_b1 + old_b2 + old_b3

    # 16位物理拆分，防止浮点计算精度溢出
    val_16 = int(new_val) & 0xFFFF
    new_b2 = val_16 & 0xFF
    new_b3 = (val_16 >> 8) & 0xFF
    new_b1 = 0x00

    new_dec_dword = (new_b3 << 24) | (new_b2 << 16) | (new_b1 << 8) | old_b0
    
    new_sum = old_b0 + new_b1 + new_b2 + new_b3
    delta = new_sum - old_sum

    new_enc_dword = encrypt_dword(new_dec_dword)
    write_dword(data, abs_offset, new_enc_dword)
    
    return delta

def update_global_checksum(data, total_delta):
    enc_dword = read_dword(data, CHECKSUM_DWORD_OFFSET)
    dec_dword = decrypt_dword(enc_dword)
    
    c0 = dec_dword & 0xFF
    c1 = (dec_dword >> 8) & 0xFF
    c2 = (dec_dword >> 16) & 0xFF
    c3 = (dec_dword >> 24) & 0xFF
    
    new_c2 = (c2 + total_delta) % 256
    
    new_dec_dword = (c3 << 24) | (new_c2 << 16) | (c1 << 8) | c0
    new_enc_dword = encrypt_dword(new_dec_dword)
    write_dword(data, CHECKSUM_DWORD_OFFSET, new_enc_dword)

def main():
    print("=" * 50)
    print(" 《心跳回忆》一代中文版 存档修改器 (支持大数版)")
    print("=" * 50)

    if not os.path.exists(FILENAME):
        print(f"❌ 错误：未能在当前目录下找到 {FILENAME} 文件！")
        return
    
    with open(FILENAME, "rb") as f:
        data = bytearray(f.read())
    
    occupied_slots = []
    for i in range(NUM_SLOTS):
        hp = get_stat_value(data, i, STATS_INFO[1]["offset"])
        if hp > 0:
            occupied_slots.append(i)
            
    if not occupied_slots:
        print("ℹ️ 提示：未检测到任何已占用的存档槽位。")
        return
    
    print("\n[+] 检测到以下已占用的存档槽位：")
    for display_idx, slot_idx in enumerate(occupied_slots, 1):
        print(f"  {display_idx}. Slot {slot_idx + 1}")
        
    try:
        sel = int(input("\n请选择要修改的槽位序号: "))
        if sel < 1 or sel > len(occupied_slots):
            print("❌ 输入无效。")
            return
        target_slot_idx = occupied_slots[sel - 1]
    except ValueError:
        print("❌ 输入必须是数字。")
        return

    pending_modifications = {}
    total_delta = 0
    
    while True:
        print(f"\n=== Slot {target_slot_idx + 1} 当前能力值 ===")
        for idx, info in STATS_INFO.items():
            curr_val = get_stat_value(data, target_slot_idx, info["offset"])
            print(f"  [{idx}] {info['name']}: {int(curr_val)}")
            
        try:
            opt = int(input("\n请选择要修改的指标序号 (输入 0 开始写入存档): "))
            if opt == 0:
                break
            if opt not in STATS_INFO:
                print("❌ 序号无效。")
                continue
                
            new_val = int(input(f"请输入【{STATS_INFO[opt]['name']}】的目标数值 (0 - 999): "))
            if new_val < 0 or new_val > 999:
                print("❌ 数值超出安全范围 (0 - 999)。")
                continue
                
            delta = modify_stat_value(data, target_slot_idx, STATS_INFO[opt]["offset"], new_val)
            total_delta += delta
            pending_modifications[STATS_INFO[opt]['name']] = new_val
            print(f"✔️ 【{STATS_INFO[opt]['name']}】已暂存修改。")
            
        except ValueError:
            print("❌ 输入错误。")
            continue

    if not pending_modifications:
        print("\nℹ️ 未做任何修改，程序退出。")
        return

    print("\n" + "=" * 30)
    print("修改汇总报告：")
    for name, val in pending_modifications.items():
        print(f"  - {name} -> 设定为 {val}")
    print("=" * 30)
    
    confirm = input("\n确认无误并开始检算校验值？(y/n): ")
    if confirm.lower() != 'y':
        print("❌ 已取消写入。")
        return

    update_global_checksum(data, total_delta)
    
    try:
        with open(OUT_FILENAME, "wb") as f:
            f.write(data)
        print(f"\n🎉 修改成功！已成功输出新存档：{OUT_FILENAME}")
        print(f"请将该文件重命名为 {FILENAME} 覆盖原存档即可。")
    except Exception as e:
        print(f"❌ 写入新存档文件失败：{e}")

if __name__ == "__main__":
    main()
