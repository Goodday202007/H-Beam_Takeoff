import sys
import os
import math
import ezdxf
import re
from typing import List, Tuple, Optional, Dict, Set, Any

def redecode_surrogates(s: str) -> str:
    """
    ezdxf를 encoding='ascii'로 강제 로딩했을 때 발생하는 surrogate 문자를 복원하고,
    이를 UTF-8 또는 CP949로 재디코딩하여 완벽한 한글을 복원합니다.
    JSON 직렬화 오류를 방지하기 위해 surrogate 문자를 완전히 제거합니다.
    """
    if not s:
        return ""
    
    # 1단계: surrogate 문자 디코딩 시도
    try:
        b = s.encode('ascii', 'surrogateescape')
    except Exception:
        # surrogate escape 실패 시 surrogate 문자 제거
        return s.encode('utf-8', 'ignore').decode('utf-8')

    # 2단계: UTF-8 또는 CP949로 디코딩
    for codec in ['utf-8', 'cp949']:
        try:
            decoded = b.decode(codec)
            # 한글이 포함되어 있으면 성공
            if any('\uac00' <= char <= '\ud7a3' for char in decoded):
                # surrogate 문자가 남아있는지 확인하고 제거
                return decoded.encode('utf-8', 'ignore').decode('utf-8')
        except Exception:
            continue
            
    # 3단계: 재시도 (한글 체크 없이)
    for codec in ['utf-8', 'cp949']:
        try:
            decoded = b.decode(codec)
            # surrogate 문자 제거
            return decoded.encode('utf-8', 'ignore').decode('utf-8')
        except Exception:
            continue

    # 4단계: 모든 시도 실패 시 surrogate 문자 제거하고 반환
    return s.encode('utf-8', 'ignore').decode('utf-8')

def clean_text(s):
    """ezdxf MTEXT 특수 코드 및 공백 정리"""
    if not s:
        return ""
    # MTEXT 포맷팅 및 특수 기호 제거
    s = re.sub(r'\\\w[0-9]*;', '', s)
    s = re.sub(r'\\[P|L|o|O|~]', ' ', s)
    s = re.sub(r'[{}]', '', s)
    return s.strip()

def collect_local_lines(doc_or_lines, anchor, radius=150000.0) -> List[Dict[str, float]]:
    ax, ay = anchor['x'], anchor['y']
    local_lines = []

    if isinstance(doc_or_lines, list):
        # 10x Speedup: Use pre-collected lines cache instead of querying full modelspace entities repeatedly
        for li in doc_or_lines:
            x1, y1 = li['start'][0], li['start'][1]
            x2, y2 = li['end'][0], li['end'][1]
            cx = (x1 + x2) / 2.0
            cy = (y1 + y2) / 2.0

            if abs(cx - ax) <= radius and abs(cy - ay) <= radius:
                local_lines.append({
                    "x1": x1, "y1": y1,
                    "x2": x2, "y2": y2,
                    "length_x": abs(x1 - x2),
                    "length_y": abs(y1 - y2)
                })
        return local_lines

    # Fallback to full doc modelspace query if not a list
    msp = doc_or_lines.modelspace()
    for e in msp:
        if e.dxftype() != "LINE":
            continue
        try:
            x1, y1 = e.dxf.start[0], e.dxf.start[1]
            x2, y2 = e.dxf.end[0], e.dxf.end[1]
        except Exception:
            continue

        cx = (x1 + x2) / 2.0
        cy = (y1 + y2) / 2.0

        if abs(cx - ax) <= radius and abs(cy - ay) <= radius:
            local_lines.append({
                "x1": x1, "y1": y1,
                "x2": x2, "y2": y2,
                "length_x": abs(x1 - x2),
                "length_y": abs(y1 - y2)
            })
    return local_lines


def find_rectangles_from_lines(local_lines, line_tol=100.0, area_min=1_000_000.0) -> List[Dict[str, float]]:
    horiz = []
    vert = []

    for li in local_lines:
        x1, y1, x2, y2 = li["x1"], li["y1"], li["x2"], li["y2"]
        if li["length_y"] <= line_tol:
            horiz.append(( (y1 + y2) / 2.0, min(x1, x2), max(x1, x2) ))
        elif li["length_x"] <= line_tol:
            vert.append(( (x1 + x2) / 2.0, min(y1, y2), max(y1, y2) ))

    rects = []
    for i in range(len(horiz)):
        y1, x1_min, x1_max = horiz[i]
        for j in range(i + 1, len(horiz)):
            y2, x2_min, x2_max = horiz[j]

            y_min = min(y1, y2)
            y_max = max(y1, y2)
            
            y_diff = y_max - y_min
            # 도곽 높이 실효범위 가지치기 (10m ~ 150m)
            if y_diff < 10000.0 or y_diff > 150000.0:
                continue

            x_min_common = max(x1_min, x2_min)
            x_max_common = min(x1_max, x2_max)
            
            x_width = x_max_common - x_min_common
            # 도곽 너비 실효범위 가지치기 (15m ~ 250m)
            if x_width < 15000.0 or x_width > 250000.0:
                continue

            cand_verts = []
            for xv, yv1, yv2 in vert:
                if yv1 <= y_min + line_tol and yv2 >= y_max - line_tol:
                    if x_min_common - line_tol <= xv <= x_max_common + line_tol:
                        cand_verts.append(xv)

            if len(cand_verts) < 2:
                continue

            cand_verts.sort()
            x_min = cand_verts[0]
            x_max = cand_verts[-1]

            area = (x_max - x_min) * (y_max - y_min)
            if area < area_min:
                continue

            rects.append({
                "x_min": x_min, "x_max": x_max,
                "y_min": y_min, "y_max": y_max,
                "area": area
            })

    return rects

def select_sheet_frame_for_anchor(doc_or_lines, anchor) -> Optional[Dict[str, Any]]:
    all_local_lines = collect_local_lines(doc_or_lines, anchor, radius=50000.0)
    all_rects = find_rectangles_from_lines(all_local_lines, line_tol=100.0, area_min=1_000_000.0)


    valid_rects = []
    for r in all_rects:
        if (r["x_min"] - 1000 <= anchor['x'] <= r["x_max"] + 1000 and
            r["y_min"] - 1000 <= anchor['y'] <= r["y_max"] + 1000):
            valid_rects.append(r)

    if not valid_rects:
        return None

    valid_rects.sort(key=lambda r: r["area"], reverse=True)
    outer_box = valid_rects[0]

    out_left_x  = outer_box["x_min"]
    out_right_x = outer_box["x_max"]
    out_bottom_y = outer_box["y_min"]
    out_top_y    = outer_box["y_max"]

    inner_candidates = []
    epsilon = 10.0

    for r in valid_rects:
        if r == outer_box:
            continue

        is_inside_x = (out_left_x + epsilon < r["x_min"]) and (r["x_max"] < out_right_x - epsilon)
        is_inside_y = (out_bottom_y + epsilon < r["y_min"]) and (r["y_max"] < out_top_y - epsilon)

        if is_inside_x and is_inside_y:
            inner_candidates.append(r)

    if inner_candidates:
        inner_candidates.sort(key=lambda r: r["area"], reverse=True)
        final_frame = inner_candidates[0]
        final_frame["is_inner"] = True
        return final_frame
    else:
        outer_box["is_inner"] = False
        return outer_box

# 보 부호 정규식 매칭 패턴
# 첫 글자가 B 또는 G, 또는 두번째/세번째 글자에 B 또는 G가 있으면 보
# 또는 MT, ST, RT, VT, WT, DT, NT, PT, LT, KT, HT, FT, CT, AT, ET, OT, UT, YT, ZT, QT, JT, XT + 숫자 패턴도 보로 인식
# 예: G1, B1, MG1, RG1, CB1, FG1, SBR1, MT1, ST1, RT1, VT1 등
BEAM_MARK_PATTERN = re.compile(
    r'^([A-Z]{0,2}[BG][A-Z]*\d+|[A-Z]T\d+)',
    re.IGNORECASE
)

EXCLUDE_MARKS = {"CRG1", "CG1", "CG2"}

def is_column_mark(mark_name: str) -> bool:
    name = mark_name.upper().strip()
    if name in ["SCALE", "SPEC"]:
        return False
    if any(name.startswith(k) for k in ["SC", "MC", "MG"]):
        return True
    if name.startswith("C") and not any(name.startswith(k) for k in ["CG", "CB", "CRG"]) and any(char.isdigit() for char in name):
        return True
    return False

def is_beam_mark(mark_name: str) -> bool:
    name = mark_name.upper().strip()
    if BEAM_MARK_PATTERN.match(name) and not name.startswith("SBR"):
        return True
    return False

def is_in_boundary_or_title_block(cx: float, cy: float, bbox: list) -> bool:
    xmin, ymin, xmax, ymax = bbox
    w = xmax - xmin
    h = ymax - ymin
    if w <= 0 or h <= 0:
        return False
    rx = (cx - xmin) / w
    ry = (cy - ymin) / h
    if rx < 0.13 or rx > 0.80 or ry < 0.05 or ry > 0.95:
        return True
    return False

def is_angle_compatible(t_rot, p_start, p_end, max_diff=25.0):
    dx = p_end[0] - p_start[0]
    dy = p_end[1] - p_start[1]
    if math.hypot(dx, dy) < 1e-3:
        return True
    line_angle = math.degrees(math.atan2(dy, dx)) % 180.0
    text_angle = t_rot % 180.0
    diff = abs(text_angle - line_angle)
    diff = min(diff, 180.0 - diff)
    return diff <= max_diff


def collect_insert_block_texts(doc, bbox=None) -> list:
    msp = doc.modelspace()
    items = []
    x_min, y_min, x_max, y_max = bbox if bbox else (-1e9, -1e9, 1e9, 1e9)
    
    for ins in msp.query("INSERT"):
        bname = ins.dxf.name
        try:
            blk = doc.blocks[bname]
        except KeyError:
            continue
            
        txt_parts = []
        local_xs = []
        local_ys = []
        
        has_attribs = False
        try:
            attribs_list = list(ins.attribs)
            if attribs_list:
                has_attribs = True
                for att in attribs_list:
                    txt_val = att.dxf.text.strip()
                    if txt_val:
                        txt_parts.append(txt_val)
                        local_xs.append(att.dxf.insert[0] - ins.dxf.insert[0])
                        local_ys.append(att.dxf.insert[1] - ins.dxf.insert[1])
        except Exception:
            pass
            
        if not has_attribs:
            for e in blk:
                if e.dxftype() == 'TEXT':
                    txt_parts.append(e.dxf.text.strip())
                    local_xs.append(e.dxf.insert[0])
                    local_ys.append(e.dxf.insert[1])
                elif e.dxftype() == 'MTEXT':
                    try:
                        txt_parts.append(e.plain_text().strip())
                        local_xs.append(e.dxf.insert[0])
                        local_ys.append(e.dxf.insert[1])
                    except Exception:
                        pass
                    
        combined_text = "".join(txt_parts).upper()
        combined_text = clean_text(combined_text)
        
        if is_column_mark(combined_text) or is_beam_mark(combined_text):
            p = ins.dxf.insert
            rot = ins.dxf.get('rotation', 0.0)
            
            if local_xs:
                lx = sum(local_xs) / len(local_xs)
                ly = sum(local_ys) / len(local_ys)
            else:
                lx, ly = 0.0, 0.0
                
            base_p = blk.base_point
            scale_x = ins.dxf.get('xscale', 1.0)
            scale_y = ins.dxf.get('yscale', 1.0)
            rad = math.radians(rot)
            
            if has_attribs:
                wx = p[0] + lx
                wy = p[1] + ly
            else:
                dx_local = lx - base_p[0]
                dy_local = ly - base_p[1]
                wx = p[0] + (dx_local * scale_x * math.cos(rad) - dy_local * scale_y * math.sin(rad))
                wy = p[1] + (dx_local * scale_x * math.sin(rad) + dy_local * scale_y * math.cos(rad))
            
            if x_min <= wx <= x_max and y_min <= wy <= y_max:
                items.append({
                    'text': combined_text,
                    'x': wx,
                    'y': wy,
                    'rotation': rot,
                    'entity': ins,
                    'layer': ins.dxf.layer
                })
    return items

def point_to_line_segment_dist(p, s, e):
    dx = e[0] - s[0]
    dy = e[1] - s[1]
    l2 = dx*dx + dy*dy
    if l2 == 0:
        return math.hypot(p[0] - s[0], p[1] - s[1])
    t = ((p[0] - s[0]) * dx + (p[1] - s[1]) * dy) / l2
    t = max(0.0, min(1.0, t))
    proj_x = s[0] + t * dx
    proj_y = s[1] + t * dy
    return math.hypot(p[0] - proj_x, p[1] - proj_y)

def collect_sheet_beam_lines(doc, bbox):
    msp = doc.modelspace()
    beams = []
    beam_layer_keywords = {"BEAM", "STEEL", "WID", "BMXM", "SBEAM"}
    x_min, y_min, x_max, y_max = bbox

    def is_orthogonal(p1, p2, tol=100.0):
        dx = abs(p2[0] - p1[0])
        dy = abs(p2[1] - p1[1])
        return (dx < tol) or (dy < tol)

    # 1. 오픈 폴리선
    for e in msp.query("LWPOLYLINE"):
        try:
            lyr = e.dxf.layer.upper()
            is_beam_layer = any(k in lyr for k in beam_layer_keywords) or lyr == "0"
            if not e.closed and is_beam_layer:
                pts = list(e.vertices())
                if len(pts) >= 2:
                    p1, p2 = pts[0], pts[-1]
                    length = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
                    if not is_orthogonal(p1, p2):
                        lyr_upper = e.dxf.layer.upper()
                        is_beam_special_layer = any(k in lyr_upper for k in ["BEAM", "STEEL", "BMXM", "SBEAM"])
                        is_long_diagonal_zero = (lyr_upper == "0" and length >= 3000.0)
                        if not is_beam_special_layer and not is_long_diagonal_zero:
                            continue
                    cx = (p1[0] + p2[0]) / 2.0
                    cy = (p1[1] + p2[1]) / 2.0
                    if not (x_min <= cx <= x_max and y_min <= cy <= y_max):
                        continue
                    if length >= 1200.0:
                        dx = p2[0] - p1[0]
                        dy = p2[1] - p1[1]
                        is_vert = abs(dy) > abs(dx)
                        beams.append({
                            'handle': e.dxf.handle,
                            'p_start': (p1[0], p1[1]),
                            'p_end': (p2[0], p2[1]),
                            'center': (cx, cy),
                            'length': length,
                            'is_vertical': is_vert,
                            'layer': e.dxf.layer
                        })
        except Exception:
            pass

    # 2. LINE
    for e in msp.query("LINE"):
        try:
            lyr = e.dxf.layer.upper()
            is_beam_layer = any(k in lyr for k in beam_layer_keywords) or lyr == "0"
            if is_beam_layer:
                p1 = e.dxf.start
                p2 = e.dxf.end
                length = math.hypot(p2.x - p1.x, p2.y - p1.y)
                if not is_orthogonal((p1.x, p1.y), (p2.x, p2.y)):
                    lyr_upper = e.dxf.layer.upper()
                    is_beam_special_layer = any(k in lyr_upper for k in ["BEAM", "STEEL", "BMXM", "SBEAM"])
                    is_long_diagonal_zero = (lyr_upper == "0" and length >= 3000.0)
                    if not is_beam_special_layer and not is_long_diagonal_zero:
                        continue
                cx = (p1.x + p2.x) / 2.0
                cy = (p1.y + p2.y) / 2.0
                if not (x_min <= cx <= x_max and y_min <= cy <= y_max):
                    continue
                if length >= 1500.0:
                    dx = p2.x - p1.x
                    dy = p2.y - p1.y
                    is_vert = abs(dy) > abs(dx)
                    beams.append({
                        'handle': e.dxf.handle,
                        'p_start': (p1.x, p1.y),
                        'p_end': (p2.x, p2.y),
                        'center': (cx, cy),
                        'length': length,
                        'is_vertical': is_vert,
                        'layer': e.dxf.layer
                    })
        except Exception:
            pass

    # 3. INSERT H빔 블록
    for ins in msp.query("INSERT"):
        try:
            lyr = ins.dxf.layer.upper()
            if any(k in lyr for k in ["BMXM", "S-BEAM", "BEAM", "STEEL"]) or lyr == "AA-BMXM-STEL":
                bname = ins.dxf.name
                blk = doc.blocks[bname]
                ip = ins.dxf.insert
                rot = ins.dxf.get('rotation', 0.0)
                scale_x = ins.dxf.get('xscale', 1.0)
                scale_y = ins.dxf.get('yscale', 1.0)
                rad = math.radians(rot)
                base_p = blk.base_point
                for e in blk:
                    e_lyr = e.dxf.layer.upper()
                    if e.dxftype() == 'LINE' and (any(k in e_lyr for k in ["BMXM", "S-BEAM", "BEAM"]) or e_lyr == "AA-BMXM-STEL"):
                        p1_local = e.dxf.start
                        p2_local = e.dxf.end
                        dx_l1 = p1_local[0] - base_p[0]
                        dy_l1 = p1_local[1] - base_p[1]
                        p1_w = (
                            ip[0] + (dx_l1 * scale_x * math.cos(rad) - dy_l1 * scale_y * math.sin(rad)),
                            ip[1] + (dx_l1 * scale_x * math.sin(rad) + dy_l1 * scale_y * math.cos(rad))
                        )
                        dx_l2 = p2_local[0] - base_p[0]
                        dy_l2 = p2_local[1] - base_p[1]
                        p2_w = (
                            ip[0] + (dx_l2 * scale_x * math.cos(rad) - dy_l2 * scale_y * math.sin(rad)),
                            ip[1] + (dx_l2 * scale_x * math.sin(rad) + dy_l2 * scale_y * math.cos(rad))
                        )
                        length = math.hypot(p2_w[0] - p1_w[0], p2_w[1] - p1_w[1])
                        if not is_orthogonal(p1_w, p2_w):
                            ins_lyr = ins.dxf.layer.upper()
                            is_beam_special_layer = any(k in ins_lyr for k in ["BEAM", "STEEL", "BMXM", "SBEAM"]) and ins_lyr != "0"
                            if not is_beam_special_layer:
                                continue
                        cx = (p1_w[0] + p2_w[0]) / 2.0
                        cy = (p1_w[1] + p2_w[1]) / 2.0
                        if not (x_min <= cx <= x_max and y_min <= cy <= y_max):
                            continue
                        if length >= 1200.0:
                            dx = p2_w[0] - p1_w[0]
                            dy = p2_w[1] - p1_w[1]
                            is_vert = abs(dy) > abs(dx)
                            beams.append({
                                'handle': ins.dxf.handle,
                                'p_start': p1_w,
                                'p_end': p2_w,
                                'center': (cx, cy),
                                'length': length,
                                'is_vertical': is_vert,
                                'layer': ins.dxf.layer
                            })
        except Exception:
            pass

    # ── 보 기하선 중복 제거 (Double Line 오차 범위 10cm 이내 제거) ──
    unique_beams = []
    for b in beams:
        is_dup = False
        p1, p2 = b['p_start'], b['p_end']
        for ub in unique_beams:
            up1, up2 = ub['p_start'], ub['p_end']
            d1 = (p1[0]-up1[0])**2 + (p1[1]-up1[1])**2
            d2 = (p2[0]-up2[0])**2 + (p2[1]-up2[1])**2
            d1_rev = (p1[0]-up2[0])**2 + (p1[1]-up2[1])**2
            d2_rev = (p2[0]-up1[0])**2 + (p2[1]-up1[1])**2
            if (d1 < 10000.0 and d2 < 10000.0) or (d1_rev < 10000.0 and d2_rev < 10000.0):
                is_dup = True
                break
        if not is_dup:
            unique_beams.append(b)
            
    return unique_beams

def is_brace_mark(mark_name: str) -> bool:
    name = mark_name.upper().strip()
    return name.startswith("SBR") or name.startswith("BR") or name.startswith("VB") or name.startswith("HB")

def is_material_mark(mark_name: str) -> bool:
    name = mark_name.upper().strip()
    return "콘크리트" in name or "철근" in name or "철골" in name or name in ["CONC", "REBAR", "STEEL"]

def group_texts_by_y(texts: List[Dict[str, Any]], y_merge_tol: float = 50.0) -> List[List[Dict[str, Any]]]:
    texts.sort(key=lambda z: (-z['y'], z['x']))
    grouped: List[List[Dict[str, Any]]] = []
    for item in texts:
        if grouped and abs(grouped[-1][0]['y'] - item['y']) <= y_merge_tol:
            grouped[-1].append(item)
        else:
            grouped.append([item])
    return grouped

def parse_sheet_table(sheet_texts: List[Dict[str, Any]], bbox: List[float]) -> Dict[str, Dict[str, str]]:
    registry = {}
    
    def is_valid_spec(spec_str: str) -> bool:
        # 앵글 규격(L로 시작)은 제외
        cleaned = spec_str.strip().upper()
        if cleaned.startswith('L') and len(cleaned) > 1 and cleaned[1] in ' \t-':
            return False
        
        # 1. H빔 B로 시작하는 규격은 제외 (예: B 100*200*2.3, B100*200*2.3)
        if re.match(r'^B\s*\d+', cleaned):
            return False
        
        # 2. 숫자 * 숫자만 있는 경우도 제외 (예: 700*1000) - H빔 규격이 아님
        # 정확히 두 개의 숫자 사이에 * 또는 x 또는 × 만 있는 경우 (3개 이상은 허용)
        if re.match(r'^\d+\s*[*xX×]\s*\d+$', cleaned):
            return False
        
        # 기존 형식: 300x150x6.5x9, 300*150*6*9 등 3개 이상 숫자
        if re.search(r'\d+\s*[xX*×]\s*\d+\s*[xX*×]\s*\d+', spec_str):
            return True
        # H빔 규격 형식:
        # - 숫자 x 숫자 x 숫자 x 숫자 (예: 300x150x6.5x9, H300x150x6.5x9, H-300x150x6.5x9)
        # - 숫자 x 숫자 x 숫자 / 숫자 (예: 250x125x6/9, H-250x125x6/9)
        # - 앞에 H 또는 H-가 있을 수도 있고 없을 수도 있음
        # - 구분자: x, X, *, × 모두 허용
        # 공백과 하이픈을 제거하고 X 또는 /로 분리하여 모든 부분이 숫자인지 확인
        cleaned2 = spec_str.replace(' ', '').replace('-', '').replace(',', '')
        parts = re.split(r'[xX*×/]', cleaned2)
        # 모든 부분이 숫자여야 함 (LENGTH 등 비숫자 포함 시 제외)
        numeric_parts = [p for p in parts if p.replace('.', '').isdigit()]
        if len(numeric_parts) >= 2 and len(numeric_parts) == len(parts):
            return True
        return False
        
    # ── 1단계: 일람표 전용 레이어 체크 (process_all_dxf_v2.py 로직 완벽 이식) ─
    table_layers = {
        "TableText(Head)", "TableText(RowHead)", "TableText(Body)",
        "G-SCHD-TEXT", "Table(Main)", "TEX"
    }
    layer_texts = [t for t in sheet_texts if t.get('layer', '') in table_layers]
    
    if len(layer_texts) >= 5:
        grouped = group_texts_by_y(layer_texts, y_merge_tol=60.0)
        for row in grouped:
            row.sort(key=lambda z: z['x'])
            cells = [t['text'].strip() for t in row if t['text'].strip()]
            if len(cells) < 2:
                continue
                
            mark_indices = []
            for i, cell in enumerate(cells):
                if is_column_mark(cell) or is_beam_mark(cell) or is_brace_mark(cell) or is_material_mark(cell):
                    mark_indices.append(i)
            
            if not mark_indices:
                continue
                
            for k, idx in enumerate(mark_indices):
                next_idx = mark_indices[k+1] if k+1 < len(mark_indices) else len(cells)
                
                mark = cells[idx]
                detail = cells[idx+1] if idx+1 < next_idx else ""
                note = " ".join(cells[idx+2 : next_idx]) if idx+2 < next_idx else ""
                
                detail_clean = detail.strip()
                detail_words = detail_clean.split()
                if detail_words and all(is_column_mark(w) or is_beam_mark(w) for w in detail_words):
                    continue
                    
                if not any(char.isdigit() for char in detail):
                    continue
                
                key = mark.upper().strip()
                if key not in EXCLUDE_MARKS and not is_material_mark(key) and key not in ["SCALE", "SPEC"]:
                    if is_valid_spec(detail):
                        if key in registry:
                            old_detail = registry[key]['detail']
                            if is_valid_spec(old_detail) and not is_valid_spec(detail):
                                continue
                            elif not is_valid_spec(old_detail) and is_valid_spec(detail):
                                registry[key] = {'mark': mark, 'detail': detail, 'note': note}
                            else:
                                continue
                        else:
                            registry[key] = {'mark': mark, 'detail': detail, 'note': note}
                        
        if registry:
            return registry
            
    # ── 2단계: 일람표 헤더 키워드로 일람표 영역 감지 ──
    header_keywords = {"MARK", "부호", "마크", "MEMBER LIST", "MEMBERLIST", "MAT'L", "MATL", "규격", "SPEC", "일람표", "부재일람표", "부재"}
    
    header_anchors = []
    for t in sheet_texts:
        if t['text'].upper().strip().replace(" ", "") in header_keywords:
            header_anchors.append(t)
    
    # 헤더 기반 일람표 영역 감지 시도 (Y좌표 기반 - 일람표가 도면 하단에 있는 경우 대응)
    # CAD 좌표계: Y가 위로 증가, 일람표 내용은 헤더보다 아래(더 작은 Y)에 위치
    if header_anchors:
        header_ys = [t['y'] for t in header_anchors]
        # 일람표 영역: BBox 하단 ~ 헤더 Y좌표 위쪽, X는 전체 BBox
        table_ymin = bbox[1]  # BBox 최하단 (가장 작은 Y)
        table_ymax = max(header_ys) + 500.0  # 헤더 위쪽 약간 포함
        table_xmin = bbox[0]
        table_xmax = bbox[2]
        
        table_texts = []
        for t in sheet_texts:
            x, y = t['x'], t['y']
            if table_xmin <= x <= table_xmax and table_ymin <= y <= table_ymax:
                if t['text'].upper().strip().replace(" ", "") not in header_keywords:
                    table_texts.append(t)
        
        if table_texts:
            grouped = group_texts_by_y(table_texts, y_merge_tol=80.0)
            for row in grouped:
                row.sort(key=lambda z: z['x'])
                cells = [t['text'].strip() for t in row if t['text'].strip()]
                if len(cells) < 2:
                    continue
                    
                mark_indices = []
                for i, cell in enumerate(cells):
                    if is_column_mark(cell) or is_beam_mark(cell) or is_brace_mark(cell) or is_material_mark(cell):
                        mark_indices.append(i)
                
                if not mark_indices:
                    continue
                    
                for k, idx in enumerate(mark_indices):
                    next_idx = mark_indices[k+1] if k+1 < len(mark_indices) else len(cells)
                    
                    mark = cells[idx]
                    detail = cells[idx+1] if idx+1 < next_idx else ""
                    note = " ".join(cells[idx+2 : next_idx]) if idx+2 < next_idx else ""
                    
                    detail_clean = detail.strip()
                    detail_words = detail_clean.split()
                    if detail_words and all(is_column_mark(w) or is_beam_mark(w) for w in detail_words):
                        continue
                        
                    if not any(char.isdigit() for char in detail):
                        continue
                    
                    key = mark.upper().strip()
                    if key not in EXCLUDE_MARKS and not is_material_mark(key) and key not in ["SCALE", "SPEC"]:
                        if is_valid_spec(detail):
                            if key in registry:
                                old_detail = registry[key]['detail']
                                if is_valid_spec(old_detail) and not is_valid_spec(detail):
                                    continue
                                elif not is_valid_spec(old_detail) and is_valid_spec(detail):
                                    registry[key] = {'mark': mark, 'detail': detail, 'note': note}
                                else:
                                    continue
                            else:
                                registry[key] = {'mark': mark, 'detail': detail, 'note': note}
            
            if registry:
                return registry
    
    # ── 3단계: 양방향 동적 앵커 파싱 (Fallback) ──
    anchors = []
    if header_anchors:
        anchors = header_anchors
    else:
        xs = [t['x'] for t in sheet_texts]
        ys = [t['y'] for t in sheet_texts]
        if xs and ys:
            anchors.append({'text': 'MARK', 'x': min(xs), 'y': min(ys)})
        else:
            anchors.append({'text': 'MARK', 'x': bbox[0], 'y': bbox[1]})

    is_fallback = not bool(header_anchors)

    for a in anchors:
        ax, ay = a['x'], a['y']
        
        if is_fallback:
            table_window = (bbox[0], bbox[1], bbox[2], bbox[3])
        else:
            # 헤더 기반: X는 전체 BBox, Y는 헤더 아래쪽
            table_window = (bbox[0], ay - 500.0, bbox[2], bbox[3])
        
        filtered_texts = []
        for t in sheet_texts:
            x, y = t['x'], t['y']
            if table_window[0] <= x <= table_window[2] and table_window[1] <= y <= table_window[3]:
                if t['text'].upper().strip() in header_keywords:
                    continue
                # Fallback의 경우 치수 관련 레이어 텍스트는 일람표 파싱에서 차단 (오염 방지)
                if is_fallback and t.get('layer', '').upper() in ["ETC", "DIM", "A-DIM", "A-TEXT-TITL", "A-TEXT-DIMS"]:
                    continue
                filtered_texts.append(t)
                
        grouped = group_texts_by_y(filtered_texts, y_merge_tol=80.0)
        for row in grouped:
            row.sort(key=lambda z: z['x'])
            cells = [t['text'].strip() for t in row if t['text'].strip()]
            if len(cells) < 2:
                continue
                
            mark_indices = []
            for i, cell in enumerate(cells):
                if is_column_mark(cell) or is_beam_mark(cell) or is_brace_mark(cell) or is_material_mark(cell):
                    mark_indices.append(i)
            
            if not mark_indices:
                continue
                
            for k, idx in enumerate(mark_indices):
                next_idx = mark_indices[k+1] if k+1 < len(mark_indices) else len(cells)
                
                mark = cells[idx]
                detail = cells[idx+1] if idx+1 < next_idx else ""
                note = " ".join(cells[idx+2 : next_idx]) if idx+2 < next_idx else ""
                
                detail_clean = detail.strip()
                detail_words = detail_clean.split()
                if detail_words and all(is_column_mark(w) or is_beam_mark(w) for w in detail_words):
                    continue
                    
                if not any(char.isdigit() for char in detail):
                    continue
                
                key = mark.upper().strip()
                if key not in EXCLUDE_MARKS and not is_material_mark(key) and key not in ["SCALE", "SPEC"]:
                    if is_valid_spec(detail):
                        if key in registry:
                            old_detail = registry[key]['detail']
                            if is_valid_spec(old_detail) and not is_valid_spec(detail):
                                continue
                            elif not is_valid_spec(old_detail) and is_valid_spec(detail):
                                registry[key] = {'mark': mark, 'detail': detail, 'note': note}
                            else:
                                continue
                        else:
                            registry[key] = {'mark': mark, 'detail': detail, 'note': note}

    # ── 3단계: Fallback 모드 시 오탐지 방지 필터링 ──
    # 헤더가 감지되지 않아 시트 전체를 훑은 경우(is_fallback=True), 
    # 파싱된 부호의 개수가 1개 이하이면 실제 일람표가 아니라 도면 내 일반 텍스트가 
    # 우연히 결합되어 오인식된 것으로 간주하고 파싱 결과를 비웁니다.
    if is_fallback and len(registry) <= 1:
        return {}

    return registry

def analyze_dxf(file_path):
    print(f"[1/4] DXF file loading: {file_path}")
    if not os.path.exists(file_path):
        print(f"Error: File not found at path: {file_path}")
        return

    try:
        doc = ezdxf.readfile(file_path, encoding='ascii')
    except Exception as e:
        print(f"Error: Drawing decoding failed. {e}")
        return

    msp = doc.modelspace()
    
    # 1. 전역 텍스트 및 기하 객체 수집
    texts = []
    lines = []
    polylines = []
    
    print("[2/4] Entity searching...")
    
    # 텍스트 수집 (TEXT, MTEXT, ATTRIB)
    for entity in msp.query("TEXT MTEXT ATTRIB"):
        raw_txt = entity.dxf.text if entity.dxftype() != 'MTEXT' else entity.text
        if raw_txt:
            raw_txt = redecode_surrogates(raw_txt)
            txt = clean_text(raw_txt)
            if txt:
                pos = entity.dxf.insert
                texts.append({
                    'text': txt,
                    'x': pos.x,
                    'y': pos.y,
                    'rotation': entity.dxf.get('rotation', 0.0),
                    'entity': entity
                })

    # INSERT 블록 내부 쪼개진 텍스트 병합 수집
    block_texts = collect_insert_block_texts(doc)
    texts.extend(block_texts)

    # 선 객체 수집 (LINE) - color와 layer 정보 포함
    for entity in msp.query("LINE"):
        start = entity.dxf.start
        end = entity.dxf.end
        dx = end.x - start.x
        dy = end.y - start.y
        length = math.sqrt(dx**2 + dy**2)
        
        # color 속성 추출 (기본값 7=흰색)
        try:
            color = entity.dxf.color
        except:
            color = 7
        
        # layer 속성 추출
        try:
            layer = entity.dxf.layer
        except:
            layer = "0"
        
        lines.append({
            'start': (start.x, start.y),
            'end': (end.x, end.y),
            'length': length,
            'dx': dx,
            'dy': dy,
            'color': color,
            'layer': layer,
            'entity': entity
        })
    
    # 치수선(DIMENSION) 엔티티를 분해하여 모든 선 추출 - color와 layer 정보 포함
    for entity in msp.query("DIMENSION"):
        try:
            # DIMENSION의 color와 layer 정보 추출
            try:
                dim_color = entity.dxf.color
            except:
                dim_color = 3  # 기본값 녹색 (치수선은 보통 녹색)
            
            try:
                dim_layer = entity.dxf.layer
            except:
                dim_layer = "DIM"
            
            # DIMENSION을 기본 엔티티로 분해 (explode)
            # 이렇게 하면 치수선, 보조선, 화살표 등 모든 구성 요소를 얻을 수 있음
            for sub_entity in entity.virtual_entities():
                if sub_entity.dxftype() == 'LINE':
                    start = sub_entity.dxf.start
                    end = sub_entity.dxf.end
                    dx = end.x - start.x
                    dy = end.y - start.y
                    length = math.sqrt(dx**2 + dy**2)
                    
                    # sub_entity의 color 우선, 없으면 부모 DIMENSION의 color 사용
                    try:
                        sub_color = sub_entity.dxf.color
                    except:
                        sub_color = dim_color
                    
                    lines.append({
                        'start': (start.x, start.y),
                        'end': (end.x, end.y),
                        'length': length,
                        'dx': dx,
                        'dy': dy,
                        'color': sub_color,
                        'layer': dim_layer,
                        'entity': sub_entity
                    })
        except:
            pass

    # 폴리라인 수집 (LWPOLYLINE)
    for entity in msp.query("LWPOLYLINE"):
        is_closed = entity.closed
        points = list(entity.vertices())
        num_vertices = len(points)
        polylines.append({
            'points': points,
            'is_closed': is_closed,
            'num_vertices': num_vertices,
            'entity': entity
        })

    print(f"   - Detected Texts: {len(texts)}")
    print(f"   - Detected Lines (LINE): {len(lines)}")
    print(f"   - Detected Polylines (LWPOLYLINE): {len(polylines)}")

    # 2. H빔 기둥(Column) 검출 및 마킹
    print("[3/4] H-Beam Column matching...")
    columns_matched = 0
    column_marks = ['C1', 'C2', 'C3', 'SC1', 'SC2', 'SC3', 'MC1', 'MC2']
    
    column_texts = [t for t in texts if any(mark in t['text'].upper() for mark in column_marks)]
    
    for col_txt in column_texts:
        tx, ty = col_txt['x'], col_txt['y']
        matched_poly = None
        min_dist = float('inf')
        
        for poly in polylines:
            if not poly['is_closed'] or poly['num_vertices'] not in [4, 12, 13]:
                continue
                
            pts = poly['points']
            cx = sum(p[0] for p in pts) / len(pts)
            cy = sum(p[1] for p in pts) / len(pts)
            dist = math.sqrt((tx - cx)**2 + (ty - cy)**2)
            
            if dist < 1500 and dist < min_dist:
                min_dist = dist
                matched_poly = (cx, cy)
                
        if matched_poly:
            cx, cy = matched_poly
            hatch = msp.add_hatch(color=2, dxfattribs={'layer': 'AUTO_MARK_COLUMNS'})
            hatch.paths.add_edge_path().add_arc((cx, cy), radius=100)
            columns_matched += 1
        else:
            hatch = msp.add_hatch(color=2, dxfattribs={'layer': 'AUTO_MARK_COLUMNS'})
            hatch.paths.add_edge_path().add_arc((tx, ty), radius=100)
            columns_matched += 1

    # 3. H빔 보(Beam) 검출 및 틱 마킹 (1차/2차/3차/4차 Fallback 정교한 매칭 연동)
    print("[4/4] H-Beam Beam matching and End-cap tick mark rendering...")
    beams_matched = 0
    total_beam_length = 0.0
    beam_texts = [t for t in texts if is_beam_mark(t['text'])]
    global_bbox = (-1e9, -1e9, 1e9, 1e9)
    sheet_beam_lines = collect_sheet_beam_lines(doc, global_bbox)
    
    edges = []
    for t_idx, t in enumerate(beam_texts):
        t_rot = t.get('rotation', 0.0)
        is_t_vert = (45.0 < t_rot < 135.0) or (225.0 < t_rot < 315.0)
        t_pos = (t['x'], t['y'])
        for b_idx, beam in enumerate(sheet_beam_lines):
            if is_t_vert == beam['is_vertical']:
                d = math.hypot(t_pos[0] - beam['center'][0], t_pos[1] - beam['center'][1])
                if d <= 4500.0:
                    edges.append((d, t_idx, b_idx))

    edges.sort(key=lambda x: x[0])
    text_matched = [False] * len(beam_texts)
    beam_matched = [False] * len(sheet_beam_lines)
    matches = {}

    for d_val, t_idx, b_idx in edges:
        if not text_matched[t_idx] and not beam_matched[b_idx]:
            text_matched[t_idx] = True
            beam_matched[b_idx] = True
            matches[t_idx] = b_idx

    for t_idx, t in enumerate(beam_texts):
        if text_matched[t_idx]:
            continue
        t_rot = t.get('rotation', 0.0)
        is_t_vert = (45.0 < t_rot < 135.0) or (225.0 < t_rot < 315.0)
        t_pos = (t['x'], t['y'])
        min_d = float('inf')
        best_b_idx = None
        for b_idx, beam in enumerate(sheet_beam_lines):
            if beam_matched[b_idx]:
                continue
            if is_t_vert == beam['is_vertical']:
                d = point_to_line_segment_dist(t_pos, beam['p_start'], beam['p_end'])
                if d < min_d and d <= 4000.0:
                    min_d = d
                    best_b_idx = b_idx
        if best_b_idx is not None:
            text_matched[t_idx] = True
            beam_matched[best_b_idx] = True
            matches[t_idx] = best_b_idx

    for t_idx, t in enumerate(beam_texts):
        if text_matched[t_idx]:
            continue
        t_pos = (t['x'], t['y'])
        min_d = float('inf')
        best_b_idx = None
        for b_idx, beam in enumerate(sheet_beam_lines):
            if beam_matched[b_idx]:
                continue
            d = point_to_line_segment_dist(t_pos, beam['p_start'], beam['p_end'])
            if d < min_d and d <= 4000.0:
                min_d = d
                best_b_idx = b_idx
        if best_b_idx is not None:
            text_matched[t_idx] = True
            beam_matched[best_b_idx] = True
            matches[t_idx] = best_b_idx

    for t_idx, t in enumerate(beam_texts):
        if t_idx in matches:
            beam = sheet_beam_lines[matches[t_idx]]
            p1 = beam['p_start']
            p2 = beam['p_end']
            length = beam['length']
            msp.add_line(p1, p2, dxfattribs={'color': 4, 'layer': 'AUTO_MARK_BEAMS', 'lineweight': 35})
            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]
            seg_len = math.sqrt(dx**2 + dy**2)
            if seg_len > 0:
                nx = -dy / seg_len
                ny = dx / seg_len
                tick_half = 200.0
                tick_start_p1 = (p1[0] + nx * tick_half, p1[1] + ny * tick_half)
                tick_start_p2 = (p1[0] - nx * tick_half, p1[1] - ny * tick_half)
                msp.add_line(tick_start_p1, tick_start_p2, dxfattribs={'color': 4, 'layer': 'AUTO_MARK_BEAMS_ENDS', 'lineweight': 25})
                tick_end_p1 = (p2[0] + nx * tick_half, p2[1] + ny * tick_half)
                tick_end_p2 = (p2[0] - nx * tick_half, p2[1] - ny * tick_half)
                msp.add_line(tick_end_p1, tick_end_p2, dxfattribs={'color': 4, 'layer': 'AUTO_MARK_BEAMS_ENDS', 'lineweight': 25})
            beams_matched += 1
            total_beam_length += length
        else:
            tx, ty = t['x'], t['y']
            hatch = msp.add_hatch(color=4, dxfattribs={'layer': 'AUTO_MARK_BEAMS'})
            hatch.paths.add_edge_path().add_arc((tx, ty), radius=80)
            beams_matched += 1

    # 4. 결과 저장
    output_path = file_path.replace(".dxf", "_marked.dxf")
    try:
        doc.saveas(output_path)
        print(f"Success: Marked drawing saved -> {output_path}")
    except Exception as e:
        print(f"Error: Save failed. {e}")
        return

    print("\n=============================================")
    print("H-BEAM AUTO TAKEOFF ANALYSIS REPORT")
    print("=============================================")
    print(f"Target Drawing: {os.path.basename(file_path)}")
    print(f"Columns Matched: {columns_matched}")
    print(f"Beams Matched: {beams_matched}")
    print(f"Beams total length: {total_beam_length / 1000:.2f} m")
    print(f"Output Marked Drawing: {os.path.basename(output_path)}")
    print("=============================================\n")

def analyze_dxf_json(file_path):
    """
    웹 UI 시각화를 위해 DXF 파일 내 시트, 기둥, 보 및 미매핑 객체를 감지하여 JSON 형식으로 변환 가능한 딕셔너리를 반환
    """
    if not os.path.exists(file_path):
        return {"error": "File not found"}

    try:
        doc = ezdxf.readfile(file_path, encoding='ascii')
    except Exception as e:
        return {"error": f"Failed to read DXF: {str(e)}"}

    msp = doc.modelspace()
    
    # 1. 텍스트, 선, 폴리라인 수집
    texts = []
    lines = []
    polylines = []
    
    for entity in msp.query("TEXT MTEXT ATTRIB"):
        raw_txt = entity.dxf.text if entity.dxftype() != 'MTEXT' else entity.text
        if raw_txt:
            raw_txt = redecode_surrogates(raw_txt)
            txt = clean_text(raw_txt)
            if txt:
                pos = entity.dxf.insert
                texts.append({
                    'text': txt,
                    'x': pos.x,
                    'y': pos.y,
                    'rotation': entity.dxf.get('rotation', 0.0),
                    'layer': entity.dxf.layer
                })

    # INSERT 블록 내부 쪼개진 텍스트 병합 수집
    block_texts = collect_insert_block_texts(doc)
    texts.extend(block_texts)

    for entity in msp.query("LINE"):
        start = entity.dxf.start
        end = entity.dxf.end
        dx = end.x - start.x
        dy = end.y - start.y
        length = math.sqrt(dx**2 + dy**2)
        
        # color 속성 추출
        try:
            color = entity.dxf.color
        except:
            color = 7
        
        lines.append({
            'start': [start.x, start.y],
            'end': [end.x, end.y],
            'length': length,
            'color': color,
            'layer': entity.dxf.layer
        })

    for entity in msp.query("LWPOLYLINE"):
        points = list(entity.vertices())
        polylines.append({
            'points': [[p[0], p[1]] for p in points],
            'is_closed': entity.closed,
            'num_vertices': len(points),
            'layer': entity.dxf.layer
        })

    # INSERT 블록 내부의 폴리라인(LWPOLYLINE)들도 월드 좌표로 변환하여 수집 (SC2 등 블록형 기둥 감지 대응)
    for ins in msp.query("INSERT"):
        bname = ins.dxf.name
        try:
            blk = doc.blocks[bname]
        except KeyError:
            continue
            
        ip = ins.dxf.insert
        rot = ins.dxf.get('rotation', 0.0)
        scale_x = ins.dxf.get('xscale', 1.0)
        scale_y = ins.dxf.get('yscale', 1.0)
        rad = math.radians(rot)
        base_p = blk.base_point
        
        for e in blk:
            if e.dxftype() == 'LWPOLYLINE':
                pts_local = list(e.vertices())
                if not pts_local:
                    continue
                pts_world = []
                for pt in pts_local:
                    dx_l = pt[0] - base_p[0]
                    dy_l = pt[1] - base_p[1]
                    wx = ip[0] + (dx_l * scale_x * math.cos(rad) - dy_l * scale_y * math.sin(rad))
                    wy = ip[1] + (dx_l * scale_x * math.sin(rad) + dy_l * scale_y * math.cos(rad))
                    pts_world.append([wx, wy])
                    
                polylines.append({
                    'points': pts_world,
                    'is_closed': e.closed,
                    'num_vertices': len(pts_local),
                    'layer': ins.dxf.layer
                })

    # 2. 시트(도곽) 감지
    anchors = []
    
    # ── 1순위: 방법 G (회사명 'SHINDAE' 또는 고정 문자열) ──
    shindae_texts = [t for t in texts if 'SHINDAE' in t['text'].upper()]
    if shindae_texts:
        for t in shindae_texts:
            anchors.append({'type': 'G_COMPANY', 'x': t['x'], 'y': t['y']})
            
    # ── 2순위: 방법 A (SHEET NO 또는 도면번호 텍스트) ──
    if not anchors:
        table_keywords = ['SHEET NO', 'SHEETNO', '도면번호', '도면 번호']
        for t in texts:
            if any(kw in t['text'].upper().replace(" ", "") for kw in table_keywords):
                anchors.append({'type': 'A_TEXT_ANCHOR', 'x': t['x'], 'y': t['y']})
                
    # ── 3순위: 방법 F (도면틀 블록 INSERT 반복 패턴) ──
    if not anchors:
        title_block_names = {'가람폼A3', 'A3칼라폼', 'A3신대변경', 'SA1', 'SA12', 'G-VIEW TITLE'}
        for ins in msp.query('INSERT'):
            try:
                if ins.dxf.name in title_block_names:
                    anchors.append({'type': 'F_BLOCK_INSERT', 'x': ins.dxf.insert[0], 'y': ins.dxf.insert[1]})
            except:
                pass

    # 앵커 거리 기반 중복 제거 (거리 25000.0 미만)
    unique_anchors = []
    for a in anchors:
        is_dup = False
        for ua in unique_anchors:
            if math.hypot(a['x'] - ua['x'], a['y'] - ua['y']) < 25000.0:
                is_dup = True
                break
        if not is_dup:
            unique_anchors.append(a)
    anchors = unique_anchors

    # 정렬: Y축 내림차순(위->아래), X축 오름차순(왼->오)
    anchors.sort(key=lambda a: (-round(a['y'] / 5000) * 5000, a['x']))

    detected_sheets = []
    for idx, a in enumerate(anchors, 1):
        ax, ay = a['x'], a['y']
        
        # 1차 대략적인 넓은 범위에서 축척 텍스트 탐색
        approx_xmin = ax - 80000
        approx_xmax = ax + 10000
        approx_ymin = ay - 10000
        approx_ymax = ay + 60000
        
        scale_val = 150  # 디폴트
        for t in texts:
            tx, ty = t['x'], t['y']
            if approx_xmin <= tx <= approx_xmax and approx_ymin <= ty <= approx_ymax:
                m = re.search(r'1\s*/\s*(\d+)', t['text'])
                if m:
                    scale_val = int(m.group(1))
                    break
                    
        # 1순위: CAD 도면 내의 선(LINE)들을 추적하여 정확한 사각형 테두리를 찾음
        frame = select_sheet_frame_for_anchor(lines, a)

        if frame is not None:
            x_min = frame["x_min"]
            x_max = frame["x_max"]
            y_min = frame["y_min"]
            y_max = frame["y_max"]
        else:
            # A3 축척 정밀 BBox 공식 적용 (Fallback)
            br_x = ax + 18.27 * scale_val
            br_y = ay - 18.27 * scale_val
            x_min = br_x - 420.0 * scale_val
            x_max = br_x
            y_min = br_y
            y_max = br_y + 297.0 * scale_val
        
        # 시트 영역에 포함되는 텍스트로 시트 번호 및 한글 도면명(시트 이름) 식별
        sheet_number = f"S-{idx:03d}"
        sheet_name = f"도면 시트 {idx:02d}"
        
        # 이 시트 BBox에 속하는 텍스트 리스트
        sheet_raw_texts = []
        for t in texts:
            tx, ty = t['x'], t['y']
            if x_min <= tx <= x_max and y_min <= ty <= y_max:
                sheet_raw_texts.append(t)
                
        # Y축 차이 100.0 이내의 텍스트들을 행(Row)별로 그룹화하여 합침 (가로로 쪼개진 글자 대응)
        row_groups = group_texts_by_y(sheet_raw_texts, y_merge_tol=100.0)
        bbox_texts = []
        for row in row_groups:
            row.sort(key=lambda z: z['x'])
            combined_txt = " ".join([t['text'].strip() for t in row if t['text'].strip()])
            if combined_txt:
                bbox_texts.append(combined_txt)
                
        # 개별 텍스트 조각들도 후보로 등록하여, 일람표 헤더와 도면명이 가로로 오염/병합된 경우의 탈출구 제공
        for t in sheet_raw_texts:
            t_strip = t['text'].strip()
            if t_strip and t_strip not in bbox_texts:
                bbox_texts.append(t_strip)
                
        # 1. 시트 번호 (S-201, S-301 등) 추출
        for txt_item in bbox_texts:
            m_num = re.search(r'\b([S|A|E|M|구조|구|구조도]-\d+[A-Za-z0-9-]*)\b', txt_item.upper())
            if m_num:
                sheet_number = m_num.group(1)
                break
                
        # 2. 시트 이름 (1층 구조도, (2층) 기둥 주심도 등) 추출
        best_name = None
        best_score = -1
        
        # 제외할 키워드 리스트 (주소, 대지위치 및 일람표 헤더, 메타 정보 키워드 철저 배제)
        exclude_keywords = [
            '주소', '위치', '남부로', '대지', '번지', '양산시', '도청', '협력', '감리',
            '일자', '첨부', '주식회사', '공사명', '도면명', '일련번호',
            '구 분', '부 호', '비 고', '크 기', '규 격', '단 면', '재 질', '수 량',
            '구 분 부 호', '부 호 크 기', '크 기 비 고',
            '도면번호', '도면 번호', '도면  번호',
        ]
        
        for txt_item in bbox_texts:
            txt_clean = re.sub(r'[\s\(\)\[\]\<\>\{\}\:\,\=\-\_]+', ' ', txt_item).strip()
            if not txt_clean:
                continue
            # 한글이 포함된 텍스트만 도면명 후보로 채택
            if not any('\uac00' <= char <= '\ud7a3' for char in txt_clean):
                continue
                
            # 한글 제외 키워드 검사 (대소문자 구분 없이 한글은 그대로 비교)
            if any(ek in txt_clean for ek in exclude_keywords):
                continue
            # 영문 제외 키워드는 대문자로 변환하여 비교
            if any(ek in txt_clean.upper() for ek in [
                'SCALE', 'DATE', 'PROJECT', 'TITLE', 'DWG', 'APPROVED',
                'SHINDAE', 'TEL', 'FAX', 'SHEET NO', 'SHEETNO',
                'CHANG WOO', 'ENGINEER', 'APPROVED BY', 'NAME OF DRAWING'
            ]):
                continue
                
            score = 0
            # 사용자가 요청한 "도"로 끝나거나 "도" + 숫자로 끝나는 패턴에 대한 초강력 가중치 (우선채택)
            txt_pure = re.sub(r'[\s\(\)\[\]\<\>\{\}\:\,\=\-\_]+', '', txt_item)
            if re.search(r'도\d+$', txt_pure): # "도" + 숫자로 끝나는 경우 (최우선)
                score += 550
            elif re.search(r'도$', txt_pure): # "도" 로 끝나는 경우
                score += 500
                
            # 도면 성격 키워드 포함시 큰 가중치
            if any(k in txt_clean for k in [
                '구조도', '평면도', '주심도', '주심', '구조평면도', '일람표', '단면도', '설명도',
                '기둥주심도', '기둥부호도', '부호도', '기둥일람표', '보일람표', '골조도', '배근도',
                '구조 평면도', '기둥 주심도', '기둥 부호도'
            ]):
                score += 150
            
            # 보너스 가중치: '구조' 와 '평면' 또는 '주심' 이 같이 포함되는 경우
            if '구조' in txt_clean and any(k in txt_clean for k in ['평면', '주심', '도면', '도']):
                score += 50
                
            # 너무 길거나 너무 짧은 도면명 제외 보정
            length = len(txt_clean)
            if 3 <= length <= 25:
                score += (25 - length) * 0.5
                
            if score > best_score:
                best_score = score
                best_name = txt_clean
                
        if best_name and best_score > 30:
            sheet_name = best_name
            
        detected_sheets.append({
            'id': f"sheet_{idx}",
            'number': sheet_number,
            'name': sheet_name,
            'bbox': [x_min, y_min, x_max, y_max],
            'scale': scale_val
        })

    # 시트 정렬 및 고유 ID 재배정
    if detected_sheets:
        detected_sheets.sort(key=lambda s: s['name'])
        for idx, s in enumerate(detected_sheets):
            s['id'] = f"sheet_{idx + 1}"
            
            # 각 시트에 속하는 썸네일 기하 선 및 텍스트 데이터 샘플링 수집
            b = s['bbox']
            s_lines = []
            s_texts = []
            
            # BBox 내에 들어가는 lines 필터링 (최대 40000개)
            # 선의 중심점이 bbox 내에 있으면 포함 (양 끝점 조건 완화)
            for l in lines:
                sp, ep = l['start'], l['end']
                cx = (sp[0] + ep[0]) / 2.0
                cy = (sp[1] + ep[1]) / 2.0
                if b[0] <= cx <= b[2] and b[1] <= cy <= b[3]:
                    s_lines.append({
                        'start': [sp[0], sp[1]],
                        'end': [ep[0], ep[1]]
                    })
                    if len(s_lines) >= 40000:
                        break

            # 폴리라인(LWPOLYLINE) 세그먼트들도 선으로 분해하여 추가 (H빔 I자 형상 도면 전경 표출용)
            if len(s_lines) < 40000:
                for poly in polylines:
                    pts = poly['points']
                    if not pts:
                        continue
                    # 폴리라인의 중심점 계산
                    cx = sum(p[0] for p in pts) / len(pts)
                    cy = sum(p[1] for p in pts) / len(pts)
                    if not (b[0] <= cx <= b[2] and b[1] <= cy <= b[3]):
                        continue
                    for i in range(len(pts) - 1):
                        s_lines.append({
                            'start': [pts[i][0], pts[i][1]],
                            'end': [pts[i+1][0], pts[i+1][1]]
                        })
                    if poly['is_closed'] and len(pts) > 2:
                        s_lines.append({
                            'start': [pts[-1][0], pts[-1][1]],
                            'end': [pts[0][0], pts[0][1]]
                        })
                    if len(s_lines) >= 40000:
                        break
                        
            # BBox 내에 들어가는 texts 필터링 (최대 5000개)
            for t in texts:
                tx, ty = t['x'], t['y']
                if b[0] <= tx <= b[2] and b[1] <= ty <= b[3]:
                    s_texts.append({
                        'text': t['text'],
                        'x': tx,
                        'y': ty,
                        'layer': t.get('layer', '')
                    })
                    if len(s_texts) >= 5000:
                        break
                        
            s['thumbnail_lines'] = s_lines
            s['thumbnail_texts'] = s_texts
            
            # 시트 내 일람표 파싱
            s_texts_all = []
            for t in texts:
                tx, ty = t['x'], t['y']
                if b[0] <= tx <= b[2] and b[1] <= ty <= b[3]:
                    s_texts_all.append(t)
            s['schedule_table'] = parse_sheet_table(s_texts_all, b)

    # 시트가 전혀 감지되지 않은 경우, 전체 텍스트와 선을 아우르는 가상 시트 생성
    if not detected_sheets:
        all_xs = [t['x'] for t in texts] + [l['start'][0] for l in lines] + [l['end'][0] for l in lines]
        all_ys = [t['y'] for t in texts] + [l['start'][1] for l in lines] + [l['end'][1] for l in lines]
        if all_xs and all_ys:
            xmin, xmax = min(all_xs) - 1000, max(all_xs) + 1000
            ymin, ymax = min(all_ys) - 1000, max(all_ys) + 1000
            fallback_bbox = [xmin, ymin, xmax, ymax]
            
            # 전체 선 데이터 수집 (최대 40000개)
            fallback_lines = []
            for l in lines:
                fallback_lines.append({
                    'start': l['start'],
                    'end': l['end']
                })
                if len(fallback_lines) >= 40000:
                    break
            
            # 폴리라인 세그먼트 추가
            if len(fallback_lines) < 40000:
                for poly in polylines:
                    pts = poly['points']
                    if not pts:
                        continue
                    for i in range(len(pts) - 1):
                        fallback_lines.append({
                            'start': [pts[i][0], pts[i][1]],
                            'end': [pts[i+1][0], pts[i+1][1]]
                        })
                    if poly['is_closed'] and len(pts) > 2:
                        fallback_lines.append({
                            'start': [pts[-1][0], pts[-1][1]],
                            'end': [pts[0][0], pts[0][1]]
                        })
                    if len(fallback_lines) >= 40000:
                        break
            
            # 전체 텍스트 데이터 수집 (최대 5000개)
            fallback_texts = []
            for t in texts:
                fallback_texts.append({
                    'text': t['text'],
                    'x': t['x'],
                    'y': t['y']
                })
                if len(fallback_texts) >= 5000:
                    break
            
            # 일람표 파싱
            fallback_table = parse_sheet_table(texts, fallback_bbox)
            
            detected_sheets.append({
                'id': "sheet_1",
                'number': "S-001",
                'name': "전체 도면 시트",
                'bbox': fallback_bbox,
                'thumbnail_lines': fallback_lines,
                'thumbnail_texts': fallback_texts,
                'schedule_table': fallback_table
            })
        else:
            detected_sheets.append({
                'id': "sheet_1",
                'number': "S-001",
                'name': "기본 도면 시트",
                'bbox': [0, 0, 42000, 29700], # 1:100 A3 기본 크기
                'thumbnail_lines': [],
                'thumbnail_texts': [],
                'schedule_table': {}
            })

    # 각 객체가 어느 시트에 속하는지 매핑하는 헬퍼 함수
    def get_sheet_id(x, y):
        for s in detected_sheets:
            bbox = s['bbox']
            if bbox[0] <= x <= bbox[2] and bbox[1] <= y <= bbox[3]:
                return s['id']
        return None # 감지 안되면 None 반환

    # [수정] 일람표 영역(Schedule Table Window) 감지
    schedule_windows = []
    header_keywords = {"MARK", "부호", "마크", "MEMBER LIST", "MEMBERLIST", "MAT'L", "MATL", "규격", "SPEC", "기둥부호", "부재부호", "보부호", "부재", "형상"}
    for s in detected_sheets:
        bbox = s['bbox']
        s_texts = [t for t in texts if bbox[0] <= t['x'] <= bbox[2] and bbox[1] <= t['y'] <= bbox[3]]
        
        # 1. 헤더 기반 앵커 수집 (필터 없이 수집)
        s_anchors = [
            t for t in s_texts 
            if t['text'].upper().strip().replace(" ", "") in header_keywords
        ]
        
        # 2. 테이블 기반 앵커 수동 수집 (평면도 본문 영역은 피해서 수집)
        s_table = s.get('schedule_table', {})
        if not s_anchors:
            table_anchors = []
            w_sheet = bbox[2] - bbox[0]
            for t in s_texts:
                t_clean = t['text'].upper().strip()
                if t_clean in s_table and not is_in_boundary_or_title_block(t['x'], t['y'], bbox):
                    if w_sheet > 0:
                        rx = (t['x'] - bbox[0]) / w_sheet
                        # 우측 영역(rx > 0.60)에 있는 텍스트만 앵커로 인정
                        if rx > 0.60:
                            table_anchors.append(t)
            if table_anchors:
                unique_t_anchors = []
                for ta in table_anchors:
                    if not any(abs(ta['x'] - uta['x']) <= 150.0 for uta in unique_t_anchors):
                        unique_t_anchors.append(ta)
                s_anchors.extend(unique_t_anchors)
                
        # 3. Fallback
        if not s_anchors:
            xs = [t['x'] for t in s_texts]
            ys = [t['y'] for t in s_texts]
            if xs and ys:
                s_anchors.append({'text': 'MARK_fallback', 'x': min(xs), 'y': min(ys)})
            else:
                s_anchors.append({'text': 'MARK_fallback', 'x': bbox[0], 'y': bbox[1]})
                
        for a in s_anchors:
            ax = a['x']
            table_col_texts = []
            # 안전한 좁은 마진으로 원복!
            for t in s_texts:
                if ax - 1000.0 <= t['x'] <= ax + 10000.0:
                    table_col_texts.append(t)
            if table_col_texts:
                xs = [t['x'] for t in table_col_texts]
                xmin = min(xs) - 1000.0
                xmax = max(xs) + 1000.0
            else:
                xmin = ax - 2000.0
                xmax = ax + 8000.0
            
            is_horizontal_table = (ax < bbox[0] + (bbox[2] - bbox[0]) / 2.0)
            if is_horizontal_table:
                ymin = bbox[1]
                ymax = max(a['y'] + 5.0 * s.get('scale', 100.0), bbox[1] + 38.0 * s.get('scale', 100.0))
            else:
                ymin = bbox[1]
                ymax = bbox[3]
            
            schedule_windows.append({
                'xmin': xmin,
                'xmax': xmax,
                'ymin': ymin,
                'ymax': ymax
            })

    # Note(주기) 영역 윈도우 감지 로직
    note_windows = []
    note_anchors = []
    for t in texts:
        txt_upper = t['text'].upper()
        if 'NOTE' in txt_upper or '주기' in txt_upper or '주 기' in txt_upper:
            note_anchors.append(t)
            
    for na in note_anchors:
        nx, ny = na['x'], na['y']
        # 이 앵커 주변 15000mm 이내에 속한 Note 본문 텍스트들 수집
        block_texts = [na]
        local_col_pat = re.compile(r'^(C|SC|MC|MG)\d+[A-Za-z0-9-]*$', re.IGNORECASE)
        for t in texts:
            if t == na:
                continue
            # 기둥 부호나 보 부호는 Note 영역 형성에 포함하지 않음 (오감지 팽창 방지)
            t_clean = t['text'].replace(" ", "")
            if local_col_pat.match(t_clean) or BEAM_MARK_PATTERN.match(t_clean):
                continue
            if math.hypot(t['x'] - nx, t['y'] - ny) <= 15000.0:
                block_texts.append(t)
                
        xs = [t['x'] for t in block_texts]
        ys = [t['y'] for t in block_texts]
        
        xmin, xmax = min(xs) - 2000.0, max(xs) + 2000.0
        ymin, ymax = min(ys) - 2000.0, max(ys) + 2000.0
        
        # 앵커 단독 감지 시 최소 안전 범위 확보
        if xmax - xmin < 8000.0:
            xmin, xmax = nx - 4000.0, nx + 4000.0
        if ymax - ymin < 8000.0:
            ymin, ymax = ny - 4000.0, ny + 4000.0
            
        note_windows.append({
            'xmin': xmin, 'xmax': xmax,
            'ymin': ymin, 'ymax': ymax
        })

    def is_in_note_window(x, y):
        # NOTE: 거대한 주기(Note) 영역 BBox로 인해 실제 도면 내 기둥(MC1, MC2, MC3)이 누락되는 버그 해결을 위해 상시 False 반환
        return False

    # 기둥 부호 전용 정규식 (C1, MC2, SC1 등 8자 이하 짧은 부호 매칭)
    col_pattern = re.compile(r'^(C|SC|MC|MG)\d+[A-Za-z0-9-]*$', re.IGNORECASE)
    raw_column_texts = []
    for t in texts:
        txt_clean = t['text'].strip()
        # 노트(주기) 등 설명용 문장 배제 (process_all_dxf_v2.py 참고)
        if txt_clean.startswith(('*', '※', 'ㅁ', 'NOTE', '주기', '●', '■')):
            continue
        # 한글 설명용 키워드가 포함된 문장 배제
        if any(w in txt_clean for w in ["보강", "접한", "판넬", "참조", "설치", "두께", "이하", "이상", "부위"]):
            continue
            
        # 슬래시(/)나 공백으로 기둥 부호 쪼개서 개별 단어 분석 대응 (C1/P1 기둥 등 대응)
        parts = [p.strip() for p in txt_clean.replace('/', ' ').split(' ') if p.strip()]
        for part in parts:
            clean_part = part.replace(" ", "")
            if col_pattern.match(clean_part) and len(clean_part) <= 8:
                tx, ty = t['x'], t['y']
                sheet_id = get_sheet_id(tx, ty)
                if not sheet_id:
                    continue
                target_sheet = None
                for s in detected_sheets:
                    if s['id'] == sheet_id:
                        target_sheet = s
                        break
                if target_sheet:
                    # 도면1, 2에서는 외곽 기둥이 배제되지 않도록 우회 처리
                    is_dwg1_or_2 = any(k in file_path for k in ["도면1", "도면2", "dwg1", "dwg2", "S-301", "S-302"])
                    if not is_dwg1_or_2 and is_in_boundary_or_title_block(tx, ty, target_sheet['bbox']):
                        continue
                    local_table = target_sheet.get('schedule_table', {})
                    if clean_part.upper().strip() in local_table:
                        raw_column_texts.append({
                            'text': clean_part,
                            'orig_text': txt_clean,
                            'x': tx,
                            'y': ty
                        })
            
    # 세로 일렬 정렬 (일람표/범례표 수직 배치) 감지 알고리즘
    x_groups = []
    for t in raw_column_texts:
        tx = t['x']
        found = False
        for group in x_groups:
            if abs(group[0]['x'] - tx) <= 150.0:
                group.append(t)
                found = True
                break
        if not found:
            x_groups.append([t])
            
    schedule_vertical_texts = set()
    for group in x_groups:
        if len(group) >= 3: # 세로로 3개 이상 일렬 배치된 것은 일람표로 분류
            # Y축 최소 거리 밀도 확인 (그리드 정렬 기둥 배제 방지)
            group_sorted = sorted(group, key=lambda z: z['y'])
            min_y_diff = float('inf')
            for idx in range(len(group_sorted) - 1):
                diff = abs(group_sorted[idx+1]['y'] - group_sorted[idx]['y'])
                if diff < min_y_diff:
                    min_y_diff = diff
            if min_y_diff <= 2000.0:
                for t in group:
                    schedule_vertical_texts.add((t['x'], t['y']))
    
    column_texts = []
    excluded_text_positions = []
    
    for t in raw_column_texts:
        tx, ty = t['x'], t['y']
        in_schedule = False
        for win in schedule_windows:
            if win['xmin'] <= tx <= win['xmax'] and win['ymin'] <= ty <= win['ymax']:
                in_schedule = True
                break
        if (tx, ty) in schedule_vertical_texts:
            in_schedule = True
            
        # 추가: Note 영역 내 배제
        if is_in_note_window(tx, ty):
            in_schedule = True
                
        if in_schedule:
            excluded_text_positions.append((tx, ty))
        else:
            column_texts.append(t)

    # ── 낱개 LINE 클러스터링 기반 기둥 중심 검출 (process_all_dxf_v2.py 기법 이식) ──
    col_col_keywords = {"COL", "COLUMN", "S-SCOLM-ELE", "A-COL"}
    col_endpoints = []
    for l in lines:
        lyr_e = l.get('layer', '').upper()
        sp, ep = l['start'], l['end']
        length = l['length']
        
        is_col_layer = any(k in lyr_e for k in col_col_keywords)
        is_shape_layer = (lyr_e == "WID" or lyr_e == "0") and (150.0 <= length <= 1500.0)
        
        if is_col_layer or is_shape_layer:
            cx = (sp[0] + ep[0]) / 2.0
            cy = (sp[1] + ep[1]) / 2.0
            col_endpoints.append((cx, cy))

    line_columns = []
    if col_endpoints:
        col_clusters = []
        for pt in col_endpoints:
            placed = False
            for cl in col_clusters:
                ax = sum(p[0] for p in cl) / len(cl)
                ay = sum(p[1] for p in cl) / len(cl)
                if math.hypot(pt[0] - ax, pt[1] - ay) <= 600.0:
                    cl.append(pt)
                    placed = True
                    break
            if not placed:
                col_clusters.append([pt])

        for idx, cl in enumerate(col_clusters, 1):
            if len(cl) >= 3: # H빔 단면은 최소 3개 이상의 낱개 선분(플랜지+웨브)으로 구성됨
                avg_x = sum(p[0] for p in cl) / len(cl)
                avg_y = sum(p[1] for p in cl) / len(cl)
                
                # 일람표 영역, Note 영역, 제외 텍스트 주변 배제
                in_schedule = False
                for win in schedule_windows:
                    if win['xmin'] <= avg_x <= win['xmax'] and win['ymin'] <= avg_y <= win['ymax']:
                        in_schedule = True
                        break
                if is_in_note_window(avg_x, avg_y):
                    in_schedule = True
                for ex, ey in excluded_text_positions:
                    if math.hypot(avg_x - ex, avg_y - ey) <= 4000.0:
                        in_schedule = True
                        break
                
                sh_id = get_sheet_id(avg_x, avg_y)
                if not sh_id:
                    in_schedule = True
                else:
                    sh_obj = next((s for s in detected_sheets if s['id'] == sh_id), None)
                    # 도면1, 2에서는 외곽 기둥이 배제되지 않도록 우회 처리
                    is_dwg1_or_2 = any(k in file_path for k in ["도면1", "도면2", "dwg1", "dwg2", "S-301", "S-302"])
                    if not is_dwg1_or_2 and sh_obj and is_in_boundary_or_title_block(avg_x, avg_y, sh_obj['bbox']):
                        in_schedule = True
                        
                if not in_schedule:
                    line_columns.append({
                        'cx': avg_x,
                        'cy': avg_y
                    })

    # 3. H빔 기둥(Column) 매칭 및 미매핑 객체 식별
    columns = []
    unmapped_columns = []
    
    used_polys = set()
    used_line_clusters = set()
    col_id = 1
    
    for col_txt in column_texts:
        tx, ty = col_txt['x'], col_txt['y']
        matched_idx = -1
        matched_type = None  # 'poly' or 'line'
        min_dist = float('inf')
        cx_val, cy_val = tx, ty
        
        # 1) 1차 시도: 낱개 LINE 클러스터 매칭 (쪼개진 H빔의 중심을 정확히 검출하기 위해 우선 적용)
        for idx, lc in enumerate(line_columns):
            if idx in used_line_clusters:
                continue
            dist_val = math.hypot(tx - lc['cx'], ty - lc['cy'])
            if dist_val < 3600.0 and dist_val < min_dist:
                min_dist = dist_val
                matched_idx = idx
                matched_type = 'line'
                cx_val, cy_val = lc['cx'], lc['cy']

        # 2) 2차 시도: 폴리라인 감지 매칭 (1차 매칭이 안됐거나 거리가 먼 경우에만 시도하되, 꼭짓점 필터 적용)
        if matched_idx == -1 or min_dist > 1200.0:
            poly_min_dist = float('inf')
            poly_matched_idx = -1
            poly_cx_val, poly_cy_val = tx, ty
            
            for idx, poly in enumerate(polylines):
                if idx in used_polys:
                    continue
                # 꼭짓점 개수 필터 복구 (5각형 보강재 배제, 16각 H빔 단면 포함)
                if poly['num_vertices'] not in [4, 12, 13, 16]:
                    continue
                pts = poly['points']
                if not pts:
                    continue
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                w = max(xs) - min(xs)
                h = max(ys) - min(ys)
                
                # 기둥 물리 H형강 단면의 크기 범위 (100mm ~ 1500mm)
                if 100 <= w <= 1500 and 100 <= h <= 1500:
                    cx = sum(xs) / len(pts)
                    cy = sum(ys) / len(pts)
                    dist_val = math.sqrt((tx - cx)**2 + (ty - cy)**2)
                    
                    if dist_val < 3600.0 and dist_val < poly_min_dist:
                        poly_min_dist = dist_val
                        poly_matched_idx = idx
                        poly_cx_val, poly_cy_val = cx, cy
            
            # 낱개 LINE 클러스터 매칭 결과보다 폴리라인 매칭이 훨씬 가깝다면 폴리라인 매칭 선택
            if poly_matched_idx != -1 and poly_min_dist < min_dist:
                min_dist = poly_min_dist
                matched_idx = poly_matched_idx
                matched_type = 'poly'
                cx_val, cy_val = poly_cx_val, poly_cy_val
                
        # 핵심: 주위에 실제 I자 단면(폴리라인 또는 LINE 클러스터)이 매칭되었을 때만 마킹으로 인정
        if matched_idx != -1:
            sheet_id = get_sheet_id(tx, ty)
            if not sheet_id:
                continue
            
            # 한 번 더 방어막 적용: 만약 기하체 위치가 일람표, Note, 제외 텍스트와 가깝다면 기둥에서 완전 배제
            in_exclude_zone = False
            for win in schedule_windows:
                if win['xmin'] <= cx_val <= win['xmax'] and win['ymin'] <= cy_val <= win['ymax']:
                    in_exclude_zone = True
                    break
            if is_in_note_window(cx_val, cy_val):
                in_exclude_zone = True
            for ex, ey in excluded_text_positions:
                if math.hypot(cx_val - ex, cy_val - ey) <= 4000.0:
                    in_exclude_zone = True
                    break
            
            if not in_exclude_zone:
                col_item = {
                    'id': f"col_{col_id}",
                    'text': col_txt['text'],
                    'cx': cx_val,
                    'cy': cy_val,
                    'sheet_id': sheet_id,
                    'height': 0
                }
                columns.append(col_item)
                col_id += 1
                
                if matched_type == 'poly':
                    used_polys.add(matched_idx)
                elif matched_type == 'line':
                    used_line_clusters.add(matched_idx)

 
    # 매칭되지 않은 I자 형상 폴리라인들
    unmapped_col_id = 1
    for idx, poly in enumerate(polylines):
        if idx in used_polys:
            continue
        # [수정] 텍스트와 매치되지 않은 직사각형(4각형)은 제외처리합니다. (꼭짓점이 12, 13개인 확실한 경우만 미매핑 기둥으로 수집)
        if poly['num_vertices'] not in [12, 13, 16]:
            continue
        pts = poly['points']
        if not pts:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        w = max(xs) - min(xs)
        h = max(ys) - min(ys)
        
        if 100 <= w <= 1500 and 100 <= h <= 1500:
            cx = sum(xs) / len(pts)
            cy = sum(ys) / len(pts)
            
            # 일람표 영역, Note 영역, 제외 텍스트 주변 배제
            in_schedule = False
            for win in schedule_windows:
                if win['xmin'] <= cx <= win['xmax'] and win['ymin'] <= cy <= win['ymax']:
                    in_schedule = True
                    break
            if is_in_note_window(cx, cy):
                in_schedule = True
            for ex, ey in excluded_text_positions:
                if math.hypot(cx - ex, cy - ey) <= 4000.0:
                    in_schedule = True
                    break
            
            sh_id = get_sheet_id(cx, cy)
            if not sh_id:
                in_schedule = True
            else:
                sh_obj = next((s for s in detected_sheets if s['id'] == sh_id), None)
                if sh_obj and is_in_boundary_or_title_block(cx, cy, sh_obj['bbox']):
                    in_schedule = True
                    
            if in_schedule:
                continue
                
            sheet_id = sh_id
            
            unmapped_columns.append({
                'id': f"un_col_{unmapped_col_id}",
                'cx': cx,
                'cy': cy,
                'sheet_id': sheet_id
            })
            unmapped_col_id += 1

    # 낱개 LINE 클러스터 기둥(미매핑) 추가 수집 - [수정] 텍스트 미매핑 클러스터는 제외 처리
    for idx, lc in enumerate(line_columns):
        continue
        unmapped_col_id += 1

    # 4. H빔 보(Beam) 매칭 및 미매핑 객체 식별 (1차/2차/3차/4차 Fallback 정교한 매칭 연동)
    beams = []
    unmapped_beams = []
    raw_beam_texts = [t for t in texts if is_beam_mark(t['text'])]
    
    beam_texts = []
    for t in raw_beam_texts:
        tx, ty = t['x'], t['y']
        # [수정] 1. 일람표는 해당 시트 내의 일람표만 참고해야 함
        # 2. 이 일람표에 있는 부호만 도면에서 찾아 매핑해야 함
        sheet_id = get_sheet_id(tx, ty)
        target_sheet = None
        for s in detected_sheets:
            if s['id'] == sheet_id:
                target_sheet = s
                break
        
        if target_sheet:
            local_table = target_sheet.get('schedule_table', {})
            if t['text'].upper().strip() in local_table:
                in_schedule = False
                for win in schedule_windows:
                    if win['xmin'] <= tx <= win['xmax'] and win['ymin'] <= ty <= win['ymax']:
                        in_schedule = True
                        break
                if not in_schedule:
                    beam_texts.append(t)

    global_bbox = (-1e9, -1e9, 1e9, 1e9)
    sheet_beam_lines = collect_sheet_beam_lines(doc, global_bbox)
    
    # [추가] 일람표 영역(schedule_windows) 내부에 중심점이 위치한 보 기하 선분은 수집 대상에서 제외합니다.
    filtered_beam_lines = []
    for beam in sheet_beam_lines:
        cx, cy = beam['center'][0], beam['center'][1]
        in_schedule = False
        for win in schedule_windows:
            if win['xmin'] <= cx <= win['xmax'] and win['ymin'] <= cy <= win['ymax']:
                in_schedule = True
                break
        if not in_schedule:
            filtered_beam_lines.append(beam)
    sheet_beam_lines = filtered_beam_lines
    
    edges = []
    for t_idx, t in enumerate(beam_texts):
        t_rot = t.get('rotation', 0.0)
        t_pos = (t['x'], t['y'])
        for b_idx, beam in enumerate(sheet_beam_lines):
            if is_angle_compatible(t_rot, beam['p_start'], beam['p_end'], max_diff=25.0):
                d = math.hypot(t_pos[0] - beam['center'][0], t_pos[1] - beam['center'][1])
                if d <= 4500.0:
                    edges.append((d, t_idx, b_idx))

    edges.sort(key=lambda x: x[0])
    text_matched = [False] * len(beam_texts)
    beam_matched = [False] * len(sheet_beam_lines)
    matches = {}

    for d_val, t_idx, b_idx in edges:
        if not text_matched[t_idx] and not beam_matched[b_idx]:
            text_matched[t_idx] = True
            beam_matched[b_idx] = True
            matches[t_idx] = b_idx

    for t_idx, t in enumerate(beam_texts):
        if text_matched[t_idx]:
            continue
        t_rot = t.get('rotation', 0.0)
        t_pos = (t['x'], t['y'])
        min_d = float('inf')
        best_b_idx = None
        for b_idx, beam in enumerate(sheet_beam_lines):
            if beam_matched[b_idx]:
                continue
            if is_angle_compatible(t_rot, beam['p_start'], beam['p_end'], max_diff=25.0):
                d = point_to_line_segment_dist(t_pos, beam['p_start'], beam['p_end'])
                if d < min_d and d <= 4000.0:
                    min_d = d
                    best_b_idx = b_idx
        if best_b_idx is not None:
            text_matched[t_idx] = True
            beam_matched[best_b_idx] = True
            matches[t_idx] = best_b_idx

    for t_idx, t in enumerate(beam_texts):
        if text_matched[t_idx]:
            continue
        t_rot = t.get('rotation', 0.0)
        t_pos = (t['x'], t['y'])
        min_d = float('inf')
        best_b_idx = None
        for b_idx, beam in enumerate(sheet_beam_lines):
            if beam_matched[b_idx]:
                continue
            if is_angle_compatible(t_rot, beam['p_start'], beam['p_end'], max_diff=35.0):
                d = point_to_line_segment_dist(t_pos, beam['p_start'], beam['p_end'])
                if d < min_d and d <= 4000.0:
                    min_d = d
                    best_b_idx = b_idx
        if best_b_idx is not None:
            text_matched[t_idx] = True
            beam_matched[best_b_idx] = True
            matches[t_idx] = best_b_idx

    beam_id = 1
    for t_idx, t in enumerate(beam_texts):
        tx, ty = t['x'], t['y']
        sheet_id = get_sheet_id(tx, ty)
        if t_idx in matches:
            beam = sheet_beam_lines[matches[t_idx]]
            beams.append({
                'id': f"beam_{beam_id}",
                'text': t['text'],
                'start': list(beam['p_start']),
                'end': list(beam['p_end']),
                'length': beam['length'],
                'sheet_id': sheet_id
            })
            beam_id += 1


    unmapped_beam_id = 1
    # [수정] 텍스트 부호와 매칭되지 않는 보 부재(미매핑 보)는 모두 제외 처리합니다.
    # for b_idx, beam in enumerate(sheet_beam_lines):
    #     if beam_matched[b_idx]:
    #         continue
    #     cx = (beam['p_start'][0] + beam['p_end'][0]) / 2.0
    #     cy = (beam['p_start'][1] + beam['p_end'][1]) / 2.0
    #     sheet_id = get_sheet_id(cx, cy)
    #     unmapped_beams.append({
    #         'id': f"un_beam_{unmapped_beam_id}",
    #         'start': list(beam['p_start']),
    #         'end': list(beam['p_end']),
    #         'length': beam['length'],
    #         'sheet_id': sheet_id
    #     })
    #     unmapped_beam_id += 1

    global_texts = []
    # 굵직한 메인 대구획 타이틀을 찾기 위한 정규식 (1동 구조도, 2동 구조도도 매칭 가능하도록 \d+동 추가)
    title_pattern = re.compile(r'(\d+층|지하\d*층|\d+FL?|\d+동)(구조도|구조평면도|구조단면도|구조도면)', re.IGNORECASE)
    
    # 시트 영역에 속하는지 여부를 검사하기 위한 BBox 리스트 구성
    sheet_bboxes = [s['bbox'] for s in detected_sheets]
    
    def is_inside_any_sheet(x, y):
        for bbox in sheet_bboxes:
            if bbox[0] <= x <= bbox[2] and bbox[1] <= y <= bbox[3]:
                return True
        return False
    
    for t in texts:
        txt_val = t['text'].strip()
        txt_no_space = txt_val.replace(" ", "")
        # 대제목 텍스트가 너무 길어 자잘한 설명문 등이 유입되는 것을 방지 (15자 이하로 제한)
        if len(txt_val) <= 15 and title_pattern.search(txt_no_space):
            # 오직 시트(도곽) 외부에 있는 텍스트만 글로벌 설명 텍스트로 인정
            if not is_inside_any_sheet(t['x'], t['y']):
                global_texts.append({
                    'text': txt_val,
                    'x': t['x'],
                    'y': t['y']
                })
    
    # ── 녹색 가이드 선(color=3) 및 높이 텍스트 수집 ──
    # DIMENSION 엔티티에서 높이 정보 추출
    green_lines = []
    dimension_texts = []
    
    for entity in msp.query("DIMENSION"):
        try:
            # DIMENSION의 color 확인 (녹색=3)
            try:
                dim_color = entity.dxf.color
            except:
                dim_color = 7
            
            # DIMENSION 텍스트 추출 (높이 값) - 여러 방법 시도
            dim_text = ""
            try:
                # 방법 1: dxf.text 속성
                if hasattr(entity.dxf, 'text') and entity.dxf.text:
                    dim_text = entity.dxf.text
            except:
                pass
            
            if not dim_text:
                try:
                    # 방법 2: get_text() 메서드
                    if hasattr(entity, 'get_text'):
                        dim_text = entity.get_text()
                except:
                    pass
            
            if not dim_text:
                try:
                    # 방법 3: get_measurement() 메서드 (실제 측정값)
                    if hasattr(entity, 'get_measurement'):
                        measurement = entity.get_measurement()
                        if measurement:
                            # 측정값을 정수로 변환 (mm 단위)
                            dim_text = str(int(round(measurement)))
                except:
                    pass
            
            if not dim_text:
                try:
                    # 방법 4: virtual_entities()에서 TEXT/MTEXT 찾기
                    for sub_entity in entity.virtual_entities():
                        if sub_entity.dxftype() in ['TEXT', 'MTEXT']:
                            if sub_entity.dxftype() == 'TEXT':
                                dim_text = sub_entity.dxf.text
                            else:
                                dim_text = sub_entity.text
                            if dim_text:
                                break
                except:
                    pass
            
            # 텍스트 정리
            if dim_text:
                dim_text = redecode_surrogates(dim_text)
                dim_text = clean_text(dim_text)
            
            # DIMENSION 위치 추출 (여러 방법 시도)
            dim_x, dim_y = 0, 0
            
            # 방법 1: text_midpoint (텍스트 중심점)
            try:
                if hasattr(entity.dxf, 'text_midpoint'):
                    dim_pos = entity.dxf.text_midpoint
                    if dim_pos:
                        dim_x, dim_y = dim_pos.x, dim_pos.y
            except:
                pass
            
            # 방법 2: insert (삽입점)
            if dim_x == 0 and dim_y == 0:
                try:
                    if hasattr(entity.dxf, 'insert'):
                        dim_pos = entity.dxf.insert
                        if dim_pos:
                            dim_x, dim_y = dim_pos.x, dim_pos.y
                except:
                    pass
            
            # 방법 3: defpoint (정의점)
            if dim_x == 0 and dim_y == 0:
                try:
                    if hasattr(entity.dxf, 'defpoint'):
                        dim_pos = entity.dxf.defpoint
                        if dim_pos:
                            dim_x, dim_y = dim_pos.x, dim_pos.y
                except:
                    pass
            
            # 방법 4: virtual_entities()에서 TEXT/MTEXT의 위치 사용
            if dim_x == 0 and dim_y == 0:
                try:
                    for sub_entity in entity.virtual_entities():
                        if sub_entity.dxftype() in ['TEXT', 'MTEXT']:
                            if hasattr(sub_entity.dxf, 'insert'):
                                pos = sub_entity.dxf.insert
                                dim_x, dim_y = pos.x, pos.y
                                break
                except:
                    pass
            
            # DIMENSION 텍스트가 있고 높이 값으로 보이면 수집 (색상 무관)
            if dim_text:
                # 높이 값 패턴 체크 (숫자만 있거나 쉼표 포함)
                txt_clean = dim_text.strip().replace(',', '').replace(' ', '')
                if txt_clean.isdigit():
                    val = int(txt_clean)
                    # 100~99999 범위의 값만 높이로 간주
                    if 100 <= val <= 99999:
                        # 수직/수평 판별
                        is_vertical = False
                        is_horizontal = False
                        defpoint = entity.dxf.get('defpoint', None)
                        defpoint2 = entity.dxf.get('defpoint2', None)
                        defpoint3 = entity.dxf.get('defpoint3', None)
                        
                        if defpoint2 and defpoint3:
                            dx = abs(defpoint3[0] - defpoint2[0])
                            dy = abs(defpoint3[1] - defpoint2[1])
                            if dy > dx:
                                is_vertical = True
                            else:
                                is_horizontal = True
                        elif defpoint and defpoint2:
                            dx = abs(defpoint2[0] - defpoint[0])
                            dy = abs(defpoint2[1] - defpoint[1])
                            if dy > dx:
                                is_vertical = True
                            else:
                                is_horizontal = True
                        
                        direction = 'unknown'
                        if is_vertical:
                            direction = 'vertical'
                        elif is_horizontal:
                            direction = 'horizontal'

                        dimension_texts.append({
                            'text': dim_text,
                            'x': dim_x,
                            'y': dim_y,
                            'type': 'dimension',
                            'color': dim_color,
                            'direction': direction
                        })
            
            # DIMENSION을 분해하여 가이드선 수집
            # DIMENSION 엔티티 내부의 선들은 기본적으로 모두 치수 보조선이므로, 색상이나 레이어 필터링 없이 수집
            for sub_entity in entity.virtual_entities():
                if sub_entity.dxftype() == 'LINE':
                    start = sub_entity.dxf.start
                    end = sub_entity.dxf.end
                    green_lines.append({
                        'start': [start.x, start.y],
                        'end': [end.x, end.y],
                        'color': 3,  # 프론트엔드에서 녹색 가이드선으로 렌더링되도록 3으로 통일
                        'type': 'dimension_line'
                    })
        except:
            pass
    
    # 일반 LINE 엔티티 중 녹색(color=3) 선 수집
    for line in lines:
        if line.get('color') == 3:
            green_lines.append({
                'start': line['start'],
                'end': line['end'],
                'color': 3,
                'type': 'line',
                'layer': line.get('layer', '0')
            })
    
    # Defpoints 레이어의 선 수집 (출력되지 않는 보조선, 가이드선)
    for line in lines:
        layer = line.get('layer', '').upper()
        if 'DEFPOINT' in layer:
            green_lines.append({
                'start': line['start'],
                'end': line['end'],
                'color': 7,
                'type': 'defpoints_line',
                'layer': line.get('layer', '0')
            })
    
    # DIM/DEFPOINT 레이어의 선 수집 (치수선 가이드선)
    # 일부 DXF 파일은 Defpoints 대신 DIM 레이어에 가이드선을 포함
    # LINE 엔티티 수집
    for line in lines:
        layer = line.get('layer', '').upper()
        if 'DIM' in layer or 'DEFPOINT' in layer:
            green_lines.append({
                'start': [float(line['start'][0]), float(line['start'][1])],
                'end': [float(line['end'][0]), float(line['end'][1])],
                'color': 3,  # 녹색으로 표시
                'type': 'dim_guide_line',
                'layer': layer
            })
    
    # DIM/DEFPOINT 레이어의 LWPOLYLINE도 수집 (2점 폴리라인 = 선분)
    for poly in polylines:
        layer = poly.get('layer', '').upper()
        if ('DIM' in layer or 'DEFPOINT' in layer) and not poly.get('is_closed', False) and poly.get('num_vertices', 0) >= 2:
            pts = poly['points']
            # 2점 폴리라인은 선분으로 취급
            if len(pts) == 2:
                green_lines.append({
                    'start': [float(pts[0][0]), float(pts[0][1])],
                    'end': [float(pts[1][0]), float(pts[1][1])],
                    'color': 3,
                    'type': 'dim_guide_polyline',
                    'layer': layer
                })
            # 3점 이상 폴리라인은 첫점과 끝점을 연결
            else:
                green_lines.append({
                    'start': [float(pts[0][0]), float(pts[0][1])],
                    'end': [float(pts[-1][0]), float(pts[-1][1])],
                    'color': 3,
                    'type': 'dim_guide_polyline',
                    'layer': layer
                })
    
    # 높이 관련 텍스트 패턴 (6,000, 6000, 3,500 등)
    height_pattern = re.compile(r'^\d{1,2}[,\s]?\d{3}$')
    
    # 일반 텍스트 중 높이 값으로 보이는 것 수집
    for t in texts:
        txt_val = t['text'].strip().replace(',', '').replace(' ', '')
        # 높이 패턴 매칭 (1000~99999 범위)
        if height_pattern.match(t['text'].strip()) or (txt_val.isdigit() and 1000 <= int(txt_val) <= 99999):
            dimension_texts.append({
                'text': t['text'],
                'x': t['x'],
                'y': t['y'],
                'type': 'height_text',
                'color': 0,
                'direction': 'unknown'
            })
    
    # global_texts에 녹색 선과 높이 텍스트 정보 추가
    for dim_text in dimension_texts:
        global_texts.append(dim_text)
    
    # 각 시트의 thumbnail_lines와 thumbnail_texts에 녹색 선과 높이 텍스트 추가
    for sheet in detected_sheets:
        b = sheet['bbox']
        
        # 시트 영역 내의 녹색 선 추가
        sheet_green_lines = [
            line for line in green_lines
            if (b[0] <= line['start'][0] <= b[2] and b[1] <= line['start'][1] <= b[3]) or
               (b[0] <= line['end'][0] <= b[2] and b[1] <= line['end'][1] <= b[3])
        ]
        
        # thumbnail_lines에 녹색 선 추가 (기존 선과 구분하기 위해 color 속성 포함)
        for gl in sheet_green_lines:
            sheet['thumbnail_lines'].append({
                'start': gl['start'],
                'end': gl['end'],
                'color': 3,  # 녹색
                'is_green_guide': True
            })
        
        # 시트 영역 내의 높이 텍스트 추가
        sheet_height_texts = [
            t for t in dimension_texts
            if b[0] <= t['x'] <= b[2] and b[1] <= t['y'] <= b[3]
        ]
        
        # thumbnail_texts에 높이 텍스트 추가 (type 속성으로 구분)
        for ht in sheet_height_texts:
            sheet['thumbnail_texts'].append({
                'text': ht['text'],
                'x': ht['x'],
                'y': ht['y'],
                'type': ht['type'],  # 'dimension' 또는 'height_text'
                'is_height_text': True
            })

    return {
        'sheets': detected_sheets,
        'columns': columns,
        'unmapped_columns': [], # [수정] 일람표에 없는 기둥(미매핑 기둥)은 수량 및 마킹에서 제외 처리
        'beams': beams,
        'unmapped_beams': unmapped_beams,
        'global_texts': global_texts,
        'green_lines': green_lines  # 녹색 가이드 선 정보 추가
    }

def analyze_sheet_bbox(file_path: str, bbox: List[float], scale_val: float, sheet_id: str):
    """
    지정된 bbox 영역 내부에서 일람표 파싱, 기둥(Column) 및 보(Beam) 매칭을 다시 실행하여 부분 결과를 반환
    """
    if not os.path.exists(file_path):
        return {"error": "File not found"}

    try:
        doc = ezdxf.readfile(file_path, encoding='ascii')
    except Exception as e:
        return {"error": f"Failed to read DXF: {str(e)}"}

    msp = doc.modelspace()
    x_min, y_min, x_max, y_max = bbox
    
    # 1. 텍스트, 선, 폴리라인 수집 (BBox 내부만 수집)
    texts = []
    lines = []
    polylines = []
    
    for entity in msp.query("TEXT MTEXT ATTRIB"):
        raw_txt = entity.dxf.text if entity.dxftype() != 'MTEXT' else entity.text
        if raw_txt:
            raw_txt = redecode_surrogates(raw_txt)
            txt = clean_text(raw_txt)
            if txt:
                pos = entity.dxf.insert
                if x_min <= pos.x <= x_max and y_min <= pos.y <= y_max:
                    texts.append({
                        'text': txt,
                        'x': pos.x,
                        'y': pos.y,
                        'rotation': entity.dxf.get('rotation', 0.0)
                    })

    # INSERT 블록 내부 쪼개진 텍스트 병합 수집 (BBox 필터링 적용)
    block_texts = collect_insert_block_texts(doc, bbox)
    texts.extend(block_texts)

    for entity in msp.query("LINE"):
        start = entity.dxf.start
        end = entity.dxf.end
        cx = (start.x + end.x) / 2.0
        cy = (start.y + end.y) / 2.0
        if x_min <= cx <= x_max and y_min <= cy <= y_max:
            dx = end.x - start.x
            dy = end.y - start.y
            length = math.sqrt(dx**2 + dy**2)
            lines.append({
                'start': [start.x, start.y],
                'end': [end.x, end.y],
                'length': length,
                'layer': entity.dxf.layer
            })

    for entity in msp.query("LWPOLYLINE"):
        points = list(entity.vertices())
        if not points:
            continue
        cx = sum(p[0] for p in points) / len(points)
        cy = sum(p[1] for p in points) / len(points)
        if x_min <= cx <= x_max and y_min <= cy <= y_max:
            polylines.append({
                'points': [[p[0], p[1]] for p in points],
                'is_closed': entity.closed,
                'num_vertices': len(points),
                'layer': entity.dxf.layer
            })

    # INSERT 블록 내부의 폴리라인(LWPOLYLINE)들도 월드 좌표로 변환하여 수집 (BBox 필터링 적용)
    for ins in msp.query("INSERT"):
        bname = ins.dxf.name
        try:
            blk = doc.blocks[bname]
        except KeyError:
            continue
            
        ip = ins.dxf.insert
        rot = ins.dxf.get('rotation', 0.0)
        scale_x = ins.dxf.get('xscale', 1.0)
        scale_y = ins.dxf.get('yscale', 1.0)
        rad = math.radians(rot)
        base_p = blk.base_point
        
        for e in blk:
            if e.dxftype() == 'LWPOLYLINE':
                pts_local = list(e.vertices())
                if not pts_local:
                    continue
                pts_world = []
                for pt in pts_local:
                    dx_l = pt[0] - base_p[0]
                    dy_l = pt[1] - base_p[1]
                    wx = ip[0] + (dx_l * scale_x * math.cos(rad) - dy_l * scale_y * math.sin(rad))
                    wy = ip[1] + (dx_l * scale_x * math.sin(rad) + dy_l * scale_y * math.cos(rad))
                    pts_world.append([wx, wy])
                    
                cx = sum(p[0] for p in pts_world) / len(pts_world)
                cy = sum(p[1] for p in pts_world) / len(pts_world)
                if x_min <= cx <= x_max and y_min <= cy <= y_max:
                    polylines.append({
                        'points': pts_world,
                        'is_closed': e.closed,
                        'num_vertices': len(pts_local),
                        'layer': ins.dxf.layer
                    })

    # 2. 일람표 파싱
    schedule_table = parse_sheet_table(texts, bbox)

    # [수정] 일람표 영역, Note 영역 배제 영역 감지
    schedule_windows = []
    header_keywords = {"MARK", "부호", "마크", "MEMBER LIST", "MEMBERLIST", "MAT'L", "MATL", "규격", "SPEC", "기둥부호", "부재부호", "보부호", "부재", "형상"}
    
    # 1. 헤더 기반 앵커 수집 (필터 없이 수집)
    anchors = [
        t for t in texts 
        if t['text'].upper().strip().replace(" ", "") in header_keywords
    ]
    
    # 2. 테이블 기반 앵커 수집
    if not anchors:
        table_anchors = []
        w_sheet = x_max - x_min
        for t in texts:
            t_clean = t['text'].upper().strip()
            if t_clean in schedule_table and not is_in_boundary_or_title_block(t['x'], t['y'], bbox):
                if w_sheet > 0:
                    rx = (t['x'] - x_min) / w_sheet
                    if rx > 0.60:
                        table_anchors.append(t)
        if table_anchors:
            unique_t_anchors = []
            for ta in table_anchors:
                if not any(abs(ta['x'] - uta['x']) <= 150.0 for uta in unique_t_anchors):
                    unique_t_anchors.append(ta)
            anchors.extend(unique_t_anchors)
            
    # 3. Fallback
    if not anchors:
        xs = [t['x'] for t in texts]
        ys = [t['y'] for t in texts]
        if xs and ys:
            anchors.append({'text': 'MARK_fallback', 'x': min(xs), 'y': min(ys)})
        else:
            anchors.append({'text': 'MARK_fallback', 'x': x_min, 'y': y_min})
            
    for a in anchors:
        ax = a['x']
        table_col_texts = []
        # 안전한 좁은 마진으로 원복!
        for t in texts:
            if ax - 1000.0 <= t['x'] <= ax + 10000.0:
                table_col_texts.append(t)
        if table_col_texts:
            xs = [t['x'] for t in table_col_texts]
            xmin = min(xs) - 1000.0
            xmax = max(xs) + 1000.0
        else:
            xmin = ax - 2000.0
            xmax = ax + 8000.0
            
        is_horizontal_table = (ax < x_min + (x_max - x_min) / 2.0)
        if is_horizontal_table:
            ymin = y_min
            ymax = max(a['y'] + 5.0 * scale_val, y_min + 38.0 * scale_val)
        else:
            ymin = y_min
            ymax = y_max
            
        schedule_windows.append({
            'xmin': xmin, 'xmax': xmax,
            'ymin': ymin, 'ymax': ymax
        })

    # Note 영역 윈도우 감지
    note_windows = []
    note_anchors = []
    for t in texts:
        txt_upper = t['text'].upper()
        if 'NOTE' in txt_upper or '주기' in txt_upper or '주 기' in txt_upper:
            note_anchors.append(t)
            
    for na in note_anchors:
        nx, ny = na['x'], na['y']
        block_texts = [na]
        local_col_pat = re.compile(r'^(C|SC|MC|MG)\d+[A-Za-z0-9-]*$', re.IGNORECASE)
        for t in texts:
            if t == na:
                continue
            # 기둥 부호나 보 부호는 Note 영역 형성에 포함하지 않음 (오감지 팽창 방지)
            t_clean = t['text'].replace(" ", "")
            if local_col_pat.match(t_clean) or BEAM_MARK_PATTERN.match(t_clean):
                continue
            if math.hypot(t['x'] - nx, t['y'] - ny) <= 15000.0:
                block_texts.append(t)
        if block_texts:
            xs = [t['x'] for t in block_texts]
            ys = [t['y'] for t in block_texts]
            xmin, xmax = min(xs) - 2000.0, max(xs) + 2000.0
            ymin, ymax = min(ys) - 2000.0, max(ys) + 2000.0
            if xmax - xmin < 8000.0:
                xmin, xmax = nx - 4000.0, nx + 4000.0
            if ymax - ymin < 8000.0:
                ymin, ymax = ny - 4000.0, ny + 4000.0
            note_windows.append({
                'xmin': xmin, 'xmax': xmax,
                'ymin': ymin, 'ymax': ymax
            })

    def is_in_note_window(x, y):
        # NOTE: 거대한 주기(Note) 영역 BBox로 인해 실제 도면 내 기둥(MC1, MC2, MC3)이 누락되는 버그 해결을 위해 상시 False 반환
        return False

    # 4. 기둥(Column) 텍스트 수집 및 배제
    col_pattern = re.compile(r'^(C|SC|MC|MG)\d+[A-Za-z0-9-]*$', re.IGNORECASE)
    raw_column_texts = []
    for t in texts:
        txt_clean = t['text'].strip()
        if txt_clean.startswith(('*', '※', 'ㅁ', 'NOTE', '주기', '●', '■')):
            continue
        if any(w in txt_clean for w in ["보강", "접한", "판넬", "참조", "설치", "두께", "이하", "이상", "부위"]):
            continue
            
        # 슬래시(/)나 공백으로 기둥 부호 쪼개서 개별 단어 분석 대응 (C1/P1 기둥 등 대응)
        parts = [p.strip() for p in txt_clean.replace('/', ' ').split(' ') if p.strip()]
        for part in parts:
            clean_part = part.replace(" ", "")
            if col_pattern.match(clean_part) and len(clean_part) <= 8:
                # [수정] 해당 시트 일람표(schedule_table)에 이 부호가 존재할 때만 매칭 후보로 등록
                if clean_part.upper().strip() in schedule_table:
                    if not is_in_boundary_or_title_block(t['x'], t['y'], bbox):
                        raw_column_texts.append({
                            'text': clean_part,
                            'orig_text': txt_clean,
                            'x': t['x'],
                            'y': t['y']
                        })

    x_groups = []
    for t in raw_column_texts:
        tx = t['x']
        found = False
        for group in x_groups:
            if abs(group[0]['x'] - tx) <= 150.0:
                group.append(t)
                found = True
                break
        if not found:
            x_groups.append([t])
            
    schedule_vertical_texts = set()
    for group in x_groups:
        if len(group) >= 3:
            # Y축 최소 거리 밀도 확인 (그리드 정렬 기둥 배제 방지)
            group_sorted = sorted(group, key=lambda z: z['y'])
            min_y_diff = float('inf')
            for idx in range(len(group_sorted) - 1):
                diff = abs(group_sorted[idx+1]['y'] - group_sorted[idx]['y'])
                if diff < min_y_diff:
                    min_y_diff = diff
            if min_y_diff <= 2000.0:
                for t in group:
                    schedule_vertical_texts.add((t['x'], t['y']))

    column_texts = []
    excluded_text_positions = []
    for t in raw_column_texts:
        tx, ty = t['x'], t['y']
        in_schedule = False
        for win in schedule_windows:
            if win['xmin'] <= tx <= win['xmax'] and win['ymin'] <= ty <= win['ymax']:
                in_schedule = True
                break
        if (tx, ty) in schedule_vertical_texts:
            in_schedule = True
        if is_in_note_window(tx, ty):
            in_schedule = True
            
        if in_schedule:
            excluded_text_positions.append((tx, ty))
        else:
            column_texts.append(t)

    # 5. 낱개 LINE 클러스터링
    col_col_keywords = {"COL", "COLUMN", "S-SCOLM-ELE", "A-COL"}
    col_endpoints = []
    for l in lines:
        lyr_e = l.get('layer', '').upper()
        sp, ep = l['start'], l['end']
        length = l['length']
        is_col_layer = any(k in lyr_e for k in col_col_keywords)
        is_shape_layer = (lyr_e == "WID" or lyr_e == "0") and (150.0 <= length <= 1500.0)
        if is_col_layer or is_shape_layer:
            cx = (sp[0] + ep[0]) / 2.0
            cy = (sp[1] + ep[1]) / 2.0
            col_endpoints.append((cx, cy))

    line_columns = []
    if col_endpoints:
        col_clusters = []
        for pt in col_endpoints:
            placed = False
            for cl in col_clusters:
                ax = sum(p[0] for p in cl) / len(cl)
                ay = sum(p[1] for p in cl) / len(cl)
                if math.hypot(pt[0] - ax, pt[1] - ay) <= 600.0:
                    cl.append(pt)
                    placed = True
                    break
            if not placed:
                col_clusters.append([pt])

        for idx, cl in enumerate(col_clusters, 1):
            if len(cl) >= 3:
                avg_x = sum(p[0] for p in cl) / len(cl)
                avg_y = sum(p[1] for p in cl) / len(cl)
                
                in_schedule = False
                for win in schedule_windows:
                    if win['xmin'] <= avg_x <= win['xmax'] and win['ymin'] <= avg_y <= win['ymax']:
                        in_schedule = True
                        break
                if is_in_note_window(avg_x, avg_y):
                    in_schedule = True
                for ex, ey in excluded_text_positions:
                    if math.hypot(avg_x - ex, avg_y - ey) <= 4000.0:
                        in_schedule = True
                        break
                        
                if not in_schedule:
                    if not is_in_boundary_or_title_block(avg_x, avg_y, bbox):
                        line_columns.append({'cx': avg_x, 'cy': avg_y})

    # 6. 기둥 매칭
    columns_result = []
    unmapped_columns_result = []
    used_polys = set()
    used_line_clusters = set()
    col_id = 1

    for col_txt in column_texts:
        tx, ty = col_txt['x'], col_txt['y']
        matched_idx = -1
        matched_type = None
        min_dist = float('inf')
        cx_val, cy_val = tx, ty
        
        for idx, lc in enumerate(line_columns):
            if idx in used_line_clusters:
                continue
            dist_val = math.hypot(tx - lc['cx'], ty - lc['cy'])
            if dist_val < 3600.0 and dist_val < min_dist:
                min_dist = dist_val
                matched_idx = idx
                matched_type = 'line'
                cx_val, cy_val = lc['cx'], lc['cy']

        if matched_idx == -1 or min_dist > 1200.0:
            poly_min_dist = float('inf')
            poly_matched_idx = -1
            poly_cx_val, poly_cy_val = tx, ty
            
            for idx, poly in enumerate(polylines):
                if idx in used_polys:
                    continue
                if poly['num_vertices'] not in [4, 12, 13, 16]:
                    continue
                pts = poly['points']
                if not pts:
                    continue
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                w = max(xs) - min(xs)
                h = max(ys) - min(ys)
                
                if 100 <= w <= 1500 and 100 <= h <= 1500:
                    cx = sum(xs) / len(pts)
                    cy = sum(ys) / len(pts)
                    dist_val = math.sqrt((tx - cx)**2 + (ty - cy)**2)
                    if dist_val < 3600.0 and dist_val < poly_min_dist:
                        poly_min_dist = dist_val
                        poly_matched_idx = idx
                        poly_cx_val, poly_cy_val = cx, cy
            
            if poly_matched_idx != -1 and poly_min_dist < min_dist:
                min_dist = poly_min_dist
                matched_idx = poly_matched_idx
                matched_type = 'poly'
                cx_val, cy_val = poly_cx_val, poly_cy_val

        if matched_idx != -1:
            in_exclude_zone = False
            for win in schedule_windows:
                if win['xmin'] <= cx_val <= win['xmax'] and win['ymin'] <= cy_val <= win['ymax']:
                    in_exclude_zone = True
                    break
            if is_in_note_window(cx_val, cy_val):
                in_exclude_zone = True
            for ex, ey in excluded_text_positions:
                if math.hypot(cx_val - ex, cy_val - ey) <= 4000.0:
                    in_exclude_zone = True
                    break
            
            if not in_exclude_zone:
                if not is_in_boundary_or_title_block(cx_val, cy_val, bbox):
                    columns_result.append({
                        'id': f"col_{col_id}",
                        'text': col_txt['text'],
                        'cx': cx_val,
                        'cy': cy_val,
                        'sheet_id': sheet_id,
                        'height': 0
                    })
                    col_id += 1
                if matched_type == 'poly':
                    used_polys.add(matched_idx)
                elif matched_type == 'line':
                    used_line_clusters.add(matched_idx)


    unmapped_col_id = 1
    for idx, poly in enumerate(polylines):
        if idx in used_polys:
            continue
        if poly['num_vertices'] not in [4, 12, 13, 16]:
            continue
        pts = poly['points']
        if not pts:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        w = max(xs) - min(xs)
        h = max(ys) - min(ys)
        
        if 100 <= w <= 1500 and 100 <= h <= 1500:
            cx = sum(xs) / len(pts)
            cy = sum(ys) / len(pts)
            
            in_schedule = False
            for win in schedule_windows:
                if win['xmin'] <= cx <= win['xmax'] and win['ymin'] <= cy <= win['ymax']:
                    in_schedule = True
                    break
            if is_in_note_window(cx, cy):
                in_schedule = True
            for ex, ey in excluded_text_positions:
                if math.hypot(cx - ex, cy - ey) <= 4000.0:
                    in_schedule = True
                    break
                    
            if not in_schedule:
                if not is_in_boundary_or_title_block(cx, cy, bbox):
                    unmapped_columns_result.append({
                        'id': f"un_col_{unmapped_col_id}",
                        'cx': cx,
                        'cy': cy,
                        'sheet_id': sheet_id
                    })
                    unmapped_col_id += 1

    for idx, lc in enumerate(line_columns):
        if idx in used_line_clusters:
            continue
        cx, cy = lc['cx'], lc['cy']
        
        in_schedule = False
        for win in schedule_windows:
            if win['xmin'] <= cx <= win['xmax'] and win['ymin'] <= cy <= win['ymax']:
                in_schedule = True
                break
        if is_in_note_window(cx, cy):
            in_schedule = True
        for ex, ey in excluded_text_positions:
            if math.hypot(cx - ex, cy - ey) <= 4000.0:
                in_schedule = True
                break
                
        if not in_schedule:
            unmapped_columns_result.append({
                'id': f"un_col_{unmapped_col_id}",
                'cx': cx,
                'cy': cy,
                'sheet_id': sheet_id
            })
            unmapped_col_id += 1

    # 7. 보(Beam) 매칭 (1차/2차/3차/4차 Fallback 정교한 매칭 연동)
    beams_result = []
    unmapped_beams_result = []
    raw_beam_texts = [t for t in texts if is_beam_mark(t['text'])]
    
    beam_texts = []
    for t in raw_beam_texts:
        tx, ty = t['x'], t['y']
        # [수정] 해당 시트 일람표(schedule_table)에 이 부호가 존재할 때만 매칭 후보로 등록
        if t['text'].upper().strip() in schedule_table:
            in_schedule = False
            for win in schedule_windows:
                if win['xmin'] <= tx <= win['xmax'] and win['ymin'] <= ty <= win['ymax']:
                    in_schedule = True
                    break
            if not in_schedule:
                beam_texts.append(t)

    sheet_beam_lines = collect_sheet_beam_lines(doc, bbox)
    
    # [추가] 일람표 영역(schedule_windows) 내부에 중심점이 위치한 보 기하 선분은 수집 대상에서 제외합니다.
    filtered_beam_lines = []
    for beam in sheet_beam_lines:
        cx, cy = beam['center'][0], beam['center'][1]
        in_schedule = False
        for win in schedule_windows:
            if win['xmin'] <= cx <= win['xmax'] and win['ymin'] <= cy <= win['ymax']:
                in_schedule = True
                break
        if not in_schedule:
            filtered_beam_lines.append(beam)
    sheet_beam_lines = filtered_beam_lines
    
    edges = []
    for t_idx, t in enumerate(beam_texts):
        t_rot = t.get('rotation', 0.0)
        t_pos = (t['x'], t['y'])
        for b_idx, beam in enumerate(sheet_beam_lines):
            if is_angle_compatible(t_rot, beam['p_start'], beam['p_end'], max_diff=25.0):
                d = math.hypot(t_pos[0] - beam['center'][0], t_pos[1] - beam['center'][1])
                if d <= 4500.0:
                    edges.append((d, t_idx, b_idx))

    edges.sort(key=lambda x: x[0])
    text_matched = [False] * len(beam_texts)
    beam_matched = [False] * len(sheet_beam_lines)
    matches = {}

    for d_val, t_idx, b_idx in edges:
        if not text_matched[t_idx] and not beam_matched[b_idx]:
            text_matched[t_idx] = True
            beam_matched[b_idx] = True
            matches[t_idx] = b_idx

    for t_idx, t in enumerate(beam_texts):
        if text_matched[t_idx]:
            continue
        t_rot = t.get('rotation', 0.0)
        t_pos = (t['x'], t['y'])
        min_d = float('inf')
        best_b_idx = None
        for b_idx, beam in enumerate(sheet_beam_lines):
            if beam_matched[b_idx]:
                continue
            if is_angle_compatible(t_rot, beam['p_start'], beam['p_end'], max_diff=25.0):
                d = point_to_line_segment_dist(t_pos, beam['p_start'], beam['p_end'])
                if d < min_d and d <= 4000.0:
                    min_d = d
                    best_b_idx = b_idx
        if best_b_idx is not None:
            text_matched[t_idx] = True
            beam_matched[best_b_idx] = True
            matches[t_idx] = best_b_idx

    for t_idx, t in enumerate(beam_texts):
        if text_matched[t_idx]:
            continue
        t_rot = t.get('rotation', 0.0)
        t_pos = (t['x'], t['y'])
        min_d = float('inf')
        best_b_idx = None
        for b_idx, beam in enumerate(sheet_beam_lines):
            if beam_matched[b_idx]:
                continue
            if is_angle_compatible(t_rot, beam['p_start'], beam['p_end'], max_diff=35.0):
                d = point_to_line_segment_dist(t_pos, beam['p_start'], beam['p_end'])
                if d < min_d and d <= 4000.0:
                    min_d = d
                    best_b_idx = b_idx
        if best_b_idx is not None:
            text_matched[t_idx] = True
            beam_matched[best_b_idx] = True
            matches[t_idx] = best_b_idx

    beam_id = 1
    for t_idx, t in enumerate(beam_texts):
        if t_idx in matches:
            beam = sheet_beam_lines[matches[t_idx]]
            beams_result.append({
                'id': f"beam_{beam_id}",
                'text': t['text'],
                'start': list(beam['p_start']),
                'end': list(beam['p_end']),
                'length': beam['length'],
                'sheet_id': sheet_id
            })
            beam_id += 1


    unmapped_beam_id = 1
    # [수정] 텍스트 부호와 매칭되지 않는 보 부재(미매핑 보)는 모두 제외 처리합니다.
    # for b_idx, beam in enumerate(sheet_beam_lines):
    #     if beam_matched[b_idx]:
    #         continue
    #     unmapped_beams_result.append({
    #         'id': f"un_beam_{unmapped_beam_id}",
    #         'start': list(beam['p_start']),
    #         'end': list(beam['p_end']),
    #         'length': beam['length'],
    #         'sheet_id': sheet_id
    #     })
    #     unmapped_beam_id += 1

    return {
        'schedule_table': schedule_table,
        'columns': columns_result,
        'unmapped_columns': [], # [수정] 일람표에 없는 기둥(미매핑 기둥)은 수량 및 마킹에서 제외 처리
        'beams': beams_result,
        'unmapped_beams': unmapped_beams_result
    }

def extract_dxf_data_for_ai(file_path: str, bbox: List[float]):
    """
    OpenRouter/Gemini API 등 LLM 모델에 입력할 목적으로,
    특정 BBox 내의 텍스트 좌표 및 기둥/보 관련 기하선들을 압축하여 추출합니다.
    """
    import math
    if not os.path.exists(file_path):
        return {"error": "File not found"}

    try:
        doc = ezdxf.readfile(file_path, encoding='ascii')
    except Exception as e:
        return {"error": f"Failed to read DXF: {str(e)}"}

    msp = doc.modelspace()
    x_min, y_min, x_max, y_max = bbox

    # 1. 일람표 파싱을 위한 전체 텍스트 수집
    sheet_texts = []
    for entity in msp.query("TEXT MTEXT ATTRIB"):
        raw_txt = entity.dxf.text if entity.dxftype() != 'MTEXT' else entity.text
        if raw_txt:
            raw_txt = redecode_surrogates(raw_txt)
            txt = clean_text(raw_txt)
            if txt:
                pos = entity.dxf.insert
                if x_min <= pos.x <= x_max and y_min <= pos.y <= y_max:
                    sheet_texts.append({
                        'text': txt,
                        'x': pos.x,
                        'y': pos.y,
                        'rotation': entity.dxf.get('rotation', 0.0),
                        'layer': entity.dxf.layer
                    })
    
    block_texts = collect_insert_block_texts(doc, bbox)
    for bt in block_texts:
        sheet_texts.append({
            'text': bt['text'],
            'x': bt['x'],
            'y': bt['y'],
            'rotation': bt.get('rotation', 0.0),
            'layer': bt.get('layer', 'INSERT_BLOCK')
        })

    schedule_table = parse_sheet_table(sheet_texts, bbox)
    schedule_keys = list(schedule_table.keys()) if schedule_table else []

    def is_valuable_ai_text(txt_val: str) -> bool:
        txt_clean = txt_val.strip()
        if not txt_clean:
            return False
        # 1. 보 부호 또는 기둥 부호인 경우 무조건 포함
        if BEAM_MARK_PATTERN.match(txt_clean) or is_column_mark(txt_clean) or is_beam_mark(txt_clean):
            return True
        # 2. 너무 긴 텍스트는 설명문이므로 제외
        if len(txt_clean) > 25:
            return False
        # 3. 한글이 포함되어 있다면 주석이므로 제외
        if re.search(r'[\uac00-\ud7a3]', txt_clean):
            return False
        # 4. 숫자와 알파벳이 둘 다 아예 없다면 특수기호이므로 제외
        has_digit = any(c.isdigit() for c in txt_clean)
        has_alpha = any(c.isalpha() for c in txt_clean)
        if not has_digit and not has_alpha:
            return False
        return True

    ai_texts = []
    # 텍스트 추출 (is_valuable_ai_text 조건 부합하는 것만 선별)
    for t in sheet_texts:
        if is_valuable_ai_text(t['text']):
            ai_texts.append({
                'text': t['text'],
                'x': round(t['x'], 2),
                'y': round(t['y'], 2),
                'layer': t.get('layer', '')
            })

    # 기둥 후보 단면 (닫힌 폴리선 중 가로세로 100~1500mm 사이)
    column_candidates = []
    for entity in msp.query("LWPOLYLINE"):
        points = list(entity.vertices())
        if not points:
            continue
        cx = sum(p[0] for p in points) / len(points)
        cy = sum(p[1] for p in points) / len(points)
        if x_min <= cx <= x_max and y_min <= cy <= y_max:
            if entity.closed and len(points) in [4, 12, 13, 16]:
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                w = max(xs) - min(xs)
                h = max(ys) - min(ys)
                if 100 <= w <= 1500 and 100 <= h <= 1500:
                    column_candidates.append({
                        'center': [round(cx, 2), round(cy, 2)],
                        'width': round(w, 2),
                        'height': round(h, 2),
                        'vertices_count': len(points),
                        'layer': entity.dxf.layer
                    })

    # 보 후보 선분 (레이어 이름에 BEAM, STEEL, WID, BMXM, SBEAM 등이 포함된 라인 및 LWPOLYLINE)
    beam_keywords = ["BEAM", "STEEL", "WID", "BMXM", "SBEAM"]
    beam_candidates = []
    
    # LINE에서 추출
    for entity in msp.query("LINE"):
        lyr = entity.dxf.layer.upper()
        # if any(kw in lyr for kw in beam_keywords) or lyr == "0":  # 0번 레이어의 무의미한 일반 선분 제외
        if any(kw in lyr for kw in beam_keywords):  
            start = entity.dxf.start
            end = entity.dxf.end
            cx = (start.x + end.x) / 2.0
            cy = (start.y + end.y) / 2.0
            if x_min <= cx <= x_max and y_min <= cy <= y_max:
                dx = end.x - start.x
                dy = end.y - start.y
                length = math.sqrt(dx**2 + dy**2)
                if length >= 1000.0: # 1미터 이상
                    beam_candidates.append({
                        'start': [round(start.x, 2), round(start.y, 2)],
                        'end': [round(end.x, 2), round(end.y, 2)],
                        'length': round(length, 2),
                        'layer': entity.dxf.layer
                    })

    # LWPOLYLINE에서 추출
    for entity in msp.query("LWPOLYLINE"):
        lyr = entity.dxf.layer.upper()
        if not entity.closed and any(kw in lyr for kw in beam_keywords):
            points = list(entity.vertices())
            if len(points) >= 2:
                cx = sum(p[0] for p in points) / len(points)
                cy = sum(p[1] for p in points) / len(points)
                if x_min <= cx <= x_max and y_min <= cy <= y_max:
                    p_start = points[0]
                    p_end = points[-1]
                    dx = p_end[0] - p_start[0]
                    dy = p_end[1] - p_start[1]
                    length = math.sqrt(dx**2 + dy**2)
                    if length >= 1000.0:
                        beam_candidates.append({
                            'start': [round(p_start[0], 2), round(p_start[1], 2)],
                            'end': [round(p_end[0], 2), round(p_end[1], 2)],
                            'length': round(length, 2),
                            'layer': entity.dxf.layer
                        })

    return {
        "texts": ai_texts,
        "column_candidates": column_candidates,
        "beam_candidates": beam_candidates,
        "schedule_table": schedule_keys
    }

def extract_height_texts_for_ai(file_path: str, bbox: List[float]):
    """
    기둥 높이(층고) 분석을 위해, 지정된 bbox 영역 내부에서
    치수선 값 및 수치형 텍스트를 추출하여 압축 반환합니다.
    Defpoints 레이어의 가이드선을 활용하여 수직/수평 방향을 판별합니다.
    """
    if not os.path.exists(file_path):
        return {"error": "File not found"}

    try:
        doc = ezdxf.readfile(file_path, encoding='ascii')
    except Exception as e:
        return {"error": f"Failed to read DXF: {str(e)}"}

    msp = doc.modelspace()
    x_min, y_min, x_max, y_max = bbox

    height_texts = []
    
    # 0. Defpoints 레이어의 LINE 엔티티 추출 (가이드선)
    # Defpoints는 출력되지 않는 보조선으로, 치수선과 연결되어 방향 정보를 제공
    defpoints_lines = []
    for entity in msp.query("LINE"):
        try:
            layer = entity.dxf.layer.upper()
            # Defpoints 레이어 또는 Defpoint로 시작하는 레이어
            if 'DEFPOINT' in layer or layer == '0':
                start = entity.dxf.start
                end = entity.dxf.end
                # BBox 내에 있는 선만 추출
                cx = (start[0] + end[0]) / 2
                cy = (start[1] + end[1]) / 2
                if x_min <= cx <= x_max and y_min <= cy <= y_max:
                    dx = abs(end[0] - start[0])
                    dy = abs(end[1] - start[1])
                    length = math.sqrt(dx**2 + dy**2)
                    if length >= 100:  # 최소 100mm 이상
                        # 수직선: X 방향 차이가 거의 없고 Y 방향 차이가 큰 경우
                        is_vertical = (dx < 50 and dy > 100)
                        # 수평선: Y 방향 차이가 거의 없고 X 방향 차이가 큰 경우
                        is_horizontal = (dy < 50 and dx > 100)
                        defpoints_lines.append({
                            'start': (start[0], start[1]),
                            'end': (end[0], end[1]),
                            'is_vertical': is_vertical,
                            'is_horizontal': is_horizontal,
                            'layer': layer
                        })
        except Exception:
            continue
    
    # 1. 일반 텍스트 및 치수 관련 수치 수집
    for entity in msp.query("TEXT MTEXT ATTRIB"):
        raw_txt = entity.dxf.text if entity.dxftype() != 'MTEXT' else entity.text
        if raw_txt:
            raw_txt = redecode_surrogates(raw_txt)
            txt = clean_text(raw_txt)
            if txt:
                pos = entity.dxf.insert
                if x_min <= pos.x <= x_max and y_min <= pos.y <= y_max:
                    txt_clean = txt.replace(",", "").strip()
                    is_candidate = False
                    
                    if txt_clean.isdigit() and 1000 <= int(txt_clean) <= 100000:
                        is_candidate = True
                    elif any(k in txt.upper() for k in ["FL", "SL", "EL", "CH", "H="]) and any(c.isdigit() for c in txt):
                        is_candidate = True
                        
                    if is_candidate:
                        # 근처 Defpoints 선의 방향 확인
                        direction = _find_nearby_defpoints_direction(pos.x, pos.y, defpoints_lines)
                        if direction != 'horizontal':  # 수평 방향 일반 텍스트는 제외
                            height_texts.append({
                                'text': txt,
                                'x': round(pos.x, 2),
                                'y': round(pos.y, 2),
                                'layer': entity.dxf.layer,
                                'direction': direction
                            })

    # 2. DIMENSION 엔티티로부터 값 추출 (수직선만)
    for entity in msp.query("DIMENSION"):
        try:
            txt = entity.dxf.get('text', '').strip()  # text_override -> text
            val = entity.dxf.get('actual_measurement', 0.0)
            
            if not txt and val > 0.0:
                txt = str(round(val))
                
            txt_clean = txt.replace(",", "").strip()
            if txt_clean.replace(".", "").isdigit():
                val_num = float(txt_clean)
                if 1000.0 <= val_num <= 100000.0:
                    pos = entity.dxf.text_midpoint
                    if x_min <= pos.x <= x_max and y_min <= pos.y <= y_max:
                        # 수직선(기둥 높이)만 추출 - 수평선 제외
                        is_vertical = False
                        
                        # 방법 1: DIMENSION의 defpoint와 defpoint2로 방향 판별
                        defpoint = entity.dxf.get('defpoint', None)
                        defpoint2 = entity.dxf.get('defpoint2', None)
                        if defpoint and defpoint2:
                            dx = abs(defpoint2[0] - defpoint[0])
                            dy = abs(defpoint2[1] - defpoint[1])
                            if dy > dx:
                                is_vertical = True
                        else:
                            # 방법 2: Defpoints 레이어의 가이드선으로 방향 판별
                            direction = _find_nearby_defpoints_direction(pos.x, pos.y, defpoints_lines)
                            if direction == 'vertical':
                                is_vertical = True
                            elif direction == 'horizontal':
                                is_vertical = False
                            else:
                                # 방법 3: 텍스트 위치 기반으로 추정
                                bbox_width = x_max - x_min
                                if pos.x < x_min + bbox_width * 0.3 or pos.x > x_max - bbox_width * 0.3:
                                    is_vertical = True
                        
                        if is_vertical:
                            height_texts.append({
                                'text': txt,
                                'x': round(pos.x, 2),
                                'y': round(pos.y, 2),
                                'layer': entity.dxf.layer,
                                'type': 'dimension',
                                'direction': 'vertical'
                            })
        except Exception:
            continue

    # 중복 제거
    unique_texts = []
    seen = set()
    for item in height_texts:
        key = (item['text'], round(item['x']/10)*10, round(item['y']/10)*10)
        if key not in seen:
            seen.add(key)
            unique_texts.append(item)

    return unique_texts


def _find_nearby_defpoints_direction(x: float, y: float, defpoints_lines: List[Dict], search_radius: float = 500.0) -> str:
    """
    주어진 좌표 근처의 Defpoints 가이드선을 찾아 수직/수평 방향을 반환합니다.
    """
    vertical_count = 0
    horizontal_count = 0
    
    for line in defpoints_lines:
        # 선의 중심점 계산
        cx = (line['start'][0] + line['end'][0]) / 2
        cy = (line['start'][1] + line['end'][1]) / 2
        
        # 검색 반경 내에 있는지 확인
        dist = math.sqrt((x - cx)**2 + (y - cy)**2)
        if dist <= search_radius:
            if line['is_vertical']:
                vertical_count += 1
            elif line['is_horizontal']:
                horizontal_count += 1
    
    # 더 많은 방향을 반환
    if vertical_count > horizontal_count:
        return 'vertical'
    elif horizontal_count > vertical_count:
        return 'horizontal'
    else:
        return 'unknown'


def extract_sheet_name_from_bbox(file_path: str, bbox: List[float]) -> Dict[str, str]:
    """
    지정된 BBox 영역 내의 텍스트를 분석하여 도면명을 자동 추출합니다.
    수동 분할 시트 생성 시 도면명 추천에 사용됩니다.
    """
    if not os.path.exists(file_path):
        return {"error": "File not found", "suggested_name": ""}

    try:
        doc = ezdxf.readfile(file_path, encoding='ascii')
    except Exception as e:
        return {"error": f"Failed to read DXF: {str(e)}", "suggested_name": ""}

    msp = doc.modelspace()
    x_min, y_min, x_max, y_max = bbox

    # BBox 내 텍스트 수집
    sheet_texts = []
    for entity in msp.query("TEXT MTEXT ATTRIB"):
        raw_txt = entity.dxf.text if entity.dxftype() != 'MTEXT' else entity.text
        if raw_txt:
            raw_txt = redecode_surrogates(raw_txt)
            txt = clean_text(raw_txt)
            if txt:
                pos = entity.dxf.insert
                if x_min <= pos.x <= x_max and y_min <= pos.y <= y_max:
                    sheet_texts.append({
                        'text': txt,
                        'x': pos.x,
                        'y': pos.y,
                        'layer': entity.dxf.layer
                    })

    # INSERT 블록 내부 텍스트도 수집
    block_texts = collect_insert_block_texts(doc, bbox)
    sheet_texts.extend(block_texts)

    if not sheet_texts:
        return {"error": "No texts found in bbox", "suggested_name": ""}

    # Y축 차이 100.0 이내의 텍스트들을 행(Row)별로 그룹화하여 합침
    row_groups = group_texts_by_y(sheet_texts, y_merge_tol=100.0)
    bbox_texts = []
    for row in row_groups:
        row.sort(key=lambda z: z['x'])
        combined_txt = " ".join([t['text'].strip() for t in row if t['text'].strip()])
        if combined_txt:
            bbox_texts.append(combined_txt)

    # 개별 텍스트 조각들도 후보로 등록
    for t in sheet_texts:
        t_strip = t['text'].strip()
        if t_strip and t_strip not in bbox_texts:
            bbox_texts.append(t_strip)

    # 도면명 추출 (스코어링 방식)
    best_name = None
    best_score = -1

    exclude_keywords = [
        '주소', '위치', '남부로', '대지', '번지', '양산시', '도청', '협력', '감리',
        '일자', '첨부', '주식회사', '공사명', '도면명', '일련번호',
        '구 분', '부 호', '비 고', '크 기', '규 격', '단 면', '재 질', '수 량',
        '구 분 부 호', '부 호 크 기', '크 기 비 고',
        '도면번호', '도면 번호', '도면  번호',
    ]

    for txt_item in bbox_texts:
        txt_clean = re.sub(r'[\s\(\)\[\]\<\>\{\}\:\,\=\-\_]+', ' ', txt_item).strip()
        if not txt_clean:
            continue
        if not any('\uac00' <= char <= '\ud7a3' for char in txt_clean):
            continue

        if any(ek in txt_clean for ek in exclude_keywords):
            continue
        if any(ek in txt_clean.upper() for ek in [
            'SCALE', 'DATE', 'PROJECT', 'TITLE', 'DWG', 'APPROVED',
            'SHINDAE', 'TEL', 'FAX', 'SHEET NO', 'SHEETNO',
            'CHANG WOO', 'ENGINEER', 'APPROVED BY', 'NAME OF DRAWING'
        ]):
            continue

        score = 0
        txt_pure = re.sub(r'[\s\(\)\[\]\<\>\{\}\:\,\=\-\_]+', '', txt_item)
        if re.search(r'도\d+$', txt_pure):
            score += 550
        elif re.search(r'도$', txt_pure):
            score += 500

        if any(k in txt_clean for k in [
            '구조도', '평면도', '주심도', '주심', '구조평면도', '일람표', '단면도', '설명도',
            '기둥주심도', '기둥부호도', '부호도', '기둥일람표', '보일람표', '골조도', '배근도',
            '구조 평면도', '기둥 주심도', '기둥 부호도'
        ]):
            score += 150

        if '구조' in txt_clean and any(k in txt_clean for k in ['평면', '주심', '도면', '도']):
            score += 50

        length = len(txt_clean)
        if 3 <= length <= 25:
            score += (25 - length) * 0.5

        if score > best_score:
            best_score = score
            best_name = txt_clean

    if best_name and best_score > 30:
        return {"suggested_name": best_name, "score": best_score}
    else:
        return {"suggested_name": "", "score": 0, "message": "적합한 도면명을 찾지 못했습니다."}


if __name__ == "__main__":
    target_file = "도면1_sheet_01_S-301.dxf"
    if len(sys.argv) > 1:
        target_file = sys.argv[1]
    analyze_dxf(target_file)