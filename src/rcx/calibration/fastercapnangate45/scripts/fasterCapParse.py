# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2024-2025, The OpenROAD Authors

import os
import re
import argparse
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


def OpenFile(file_path, rw="r"):
    if rw == "r":
        if os.path.exists(file_path):
            # print(file_path)
            return open(file_path, rw)
        else:
            print(f"The file {file_path} does not exist.")
            exit()
    if rw == "w":
        return open(file_path, rw)


def getWSformat(sp):
    dist = "{:.4f}".format(sp)
    return dist


def getFF(cap):
    cc = "{:9.6f}".format(cap * 1e15)
    return cc


def getWS(word, SW, ii):
    # parsing W0.14_W0.14
    s1 = float(word.split("_")[ii].split(SW)[1])
    return s1


# g2_wire_M5_w0  -7.3632e-17 2.82679e-16 -1.01845e-16 -5.93445e-17 -5.83917e-17 -5.96175e-17 -1.01798e-16
# g3_wire_M4_w1  -1.41823e-16 -2.30241e-17 5.5345e-16 -2.76143e-16 -3.19856e-18 1.15872e-18 -2.70547e-20


def parseMatrixRow(row, met, matrixRowIndex, wireCnt, diagWireCnt, dbg=0):
    # process one row of cap matrix at a time
    # returns wire index last number of the first column
    # return diagonal cap value for the wire index
    # return total coupling left and right of diagonal
    # return 2 caps left and right after immediate left and right
    # return diag cap as the before last column

    capValues = row.split()
    ii = matrixRowIndex

    # g3_wire_M4_w1
    targetMetWord = "_M" + str(met) + "_"

    if dbg > 0:
        print("-------------------------------------------------")
        print(row)
    if dbg > 1:
        print("targetMetWord= ", targetMetWord)

    if targetMetWord not in capValues[0]:
        return []

    wireIndex = int(capValues[0].split("w")[2])
    if wireIndex == 0:
        return []

    preWireCnt = matrixRowIndex - wireIndex
    diagWireIndex = preWireCnt + wireCnt
    if dbg > 1:
        print("wire= ", wireIndex)
        print("preWireCnt= ", preWireCnt)
        print("diagWireIndex= ", diagWireIndex)

    # diagonal
    tot = float(capValues[ii])
    cc = 0.0
    if wireIndex > 1:
        cc += float(capValues[ii - 1])
    if wireIndex + 1 <= wireCnt:
        cc += float(capValues[ii + 1])

    cc2 = 0.0
    if wireIndex > 2:
        cc2 += float(capValues[ii - 2])
    if wireIndex + 2 <= wireCnt:
        cc2 += float(capValues[ii + 2])

    diagCC = []
    for i in range(1, diagWireCnt + 1):
        jj = i + diagWireIndex
        diagCC.append(-float(capValues[jj]))

    return [wireIndex, tot, -cc, -cc2, diagCC]


def getWireCnt(capMatrix, mets, dbg=0):
    # returns wireCnt of target met=met and cnt of diagonal wires
    # skipping the context conductors
    # traverses all the rows of the cap matrix looking for patterns like _M2_
    diag = mets[3]
    met = mets[0]
    metUnder = mets[1]
    metOver = mets[2]

    # _M3_
    targetMetWord = "_M" + str(met) + "_"
    targetDiagMetWord = ""
    if diag:
        targetDiagMetWord = "_M" + str(metOver) + "_"

    wireCnt = 0
    diagWireCnt = 0
    for i in range(len(capMatrix)):
        name = capMatrix[i].split()[0]
        if dbg > 0:
            print(name)

        if targetMetWord in name:
            wireCnt = wireCnt + 1
        if diag and targetDiagMetWord in name:
            diagWireCnt = diagWireCnt + 1
            continue
    if dbg > 0:
        print(targetMetWord, targetDiagMetWord, [wireCnt, diagWireCnt])

    return [wireCnt, diagWireCnt]


def getPatternName(word):
    # returns last 4 subwords of the Input Pattern Name

    n = len(word)
    name = ""
    for i in range(6, 1, -1):
        name += word[n - i]
        name += "/"
    return name


def getMets(word):
    # returns metal indices from the pattern
    diag = 0
    met = 0
    metOver = 0
    metUnder = 0

    over = word.split("o")
    # print(over)
    if len(over) > 1:
        met = over[0].split("M")[1]
        mu = over[1].split("u")
        metUnder = mu[0].split("M")[1]
        if len(mu) > 1:
            metOver = mu[1].split("M")[1]
    else:
        under = word.split("u")
        # Diag M1duM3
        if "d" in under[0]:
            diag = 1
            met = under[0].split("d")[0].split("M")[1]
        else:
            met = under[0].split("M")[1]

        metOver = under[1].split("M")[1]

    return [met, metUnder, metOver, diag]


def matrix_rows_to_float(row_strings):
    names = []
    mat = []
    for row in row_strings:
        toks = row.split()
        names.append(toks[0])
        mat.append([float(x) for x in toks[1:]])
    return names, mat


def float_matrix_to_rows(names, mat):
    out = []
    for i, name in enumerate(names):
        vals = " ".join(f"{v:.6e}" for v in mat[i])
        out.append(f"{name}  {vals} ")
    return out


def conductor_block_max_rel_asym(matrix, min_abs=1e-16):
    """Max |Cij-Cji|/max(|Cij|,|Cji|) on conductor block (drop M0 row/col)."""
    if len(matrix) <= 1:
        return 0.0
    sub = [row[1:] for row in matrix[1:]]
    return _matrix_max_rel_asym(sub, min_abs)


def _matrix_max_rel_asym(matrix, min_abs=1e-16):
    n = len(matrix)
    max_rel = 0.0
    for i in range(n):
        for j in range(i + 1, n):
            a, b = matrix[i][j], matrix[j][i]
            ref = max(abs(a), abs(b))
            if ref < min_abs:
                continue
            max_rel = max(max_rel, abs(a - b) / ref)
    return max_rel


def _load_quality_gate():
    import importlib.util

    # fasterCapParse may live under fastercapnangate45 while matrix_quality_gate
    # is maintained under fastercap_sky130hd (symlinked parser).
    candidates = [
        _SCRIPT_DIR / "matrix_quality_gate.py",
        _SCRIPT_DIR.parent.parent / "fastercap_sky130hd" / "scripts" / "matrix_quality_gate.py",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        spec = importlib.util.spec_from_file_location("matrix_quality_gate", path)
        if spec is None or spec.loader is None:
            continue
        mod = importlib.util.module_from_spec(spec)
        sys.modules["matrix_quality_gate"] = mod
        spec.loader.exec_module(mod)
        return mod.GateConfig, mod.evaluate_matrix_quality_gate
    raise ImportError(
        "matrix_quality_gate not found; expected fastercapnangate45/scripts "
        "or fastercap_sky130hd/scripts"
    )


def symmetrize_off_diagonal_avg(matrix):
    """Average mutual entries: Cij=Cji=(Cij+Cji)/2 for i!=j."""
    n = len(matrix)
    for i in range(n):
        for j in range(i + 1, n):
            avg = (matrix[i][j] + matrix[j][i]) / 2.0
            matrix[i][j] = avg
            matrix[j][i] = avg
    return matrix


def readFasterCapOutPutLog(
    in_file,
    out_file,
    warnFP,
    emptyFP,
    statsFP,
    dbg,
    lenMetaFP=None,
    symmetrize_avg=False,
    quality_gate=None,
    skip_qualityFP=None,
):
    # reads the log file and parses the cap values for all conductors from the last valid iteration

    if dbg > 1:
        print(in_file)

    iterCnt = 0
    dimension = 0
    capMatrixCompleted = 0
    lastIterationIndex = 0
    iteration = []
    rows = []
    patternName = ""
    # Some failed FasterCap logs do not contain "Input file:" header.
    # Keep a safe fallback to avoid UnboundLocalError in warnings.
    full_pattern_file = in_file
    spacings = []
    widths = []
    mets = []
    patternType = ""
    len_in_widths = 0
    physical_len_um = 0.0

    mbytes = 0
    secs = 0

    line_cnt = 0
    f = OpenFile(in_file)
    for line in f:
        line_cnt = line_cnt + 1
        # parsing OverUnder5/M4oM3uM5/W0.14_W0.14/S0.14_S0.14/wires.lst
        if "Input file:" in line:
            file_line = line.split()
            full_pattern_file = file_line[2]

            # old flow word= file_line[2].split('/')
            word = in_file.split("/")
            n = len(word)
            if dbg > 0:
                print("Parsing Pattern: ", file_line[2])

            patternName = getPatternName(word)
            spacings = [getWS(word[n - 2], "S", 0), getWS(word[n - 2], "S", 1)]
            widths = [getWS(word[n - 3], "W", 0), getWS(word[n - 3], "W", 1)]
            len_in_widths = int(word[n - 2].split("L")[1])
            # IMPORTANT:
            # - LEN in pattern names (e.g. L10) is a multiplier in units of target wire
            #   width, NOT an absolute physical length in um.
            # - OpenRCX parser reads LEN as an integer multiplier from the caps line.
            #   Keep writing LEN as multiplier for compatibility.
            # Physical length for bookkeeping:
            #   physical_len_um = len_in_widths * width_um
            physical_len_um = len_in_widths * widths[0]
            mets = getMets(word[n - 4])
            patternType = word[n - 5]
            if dbg > 1:
                print(
                    patternName,
                    spacings,
                    widths,
                    mets,
                    len_in_widths,
                    "physical_len_um=",
                    physical_len_um,
                )
            continue

        if "Iteration number" in line:
            iterCnt = iterCnt + 1
            rows = []
            continue

        if "Dimension" in line:
            capMatrixCompleted = 0
            dimension = int(line.split()[1])
            continue

        # Total allocated memory: 1439880 kilobytes
        # Total time: 375.292633s (0 days, 0 hours, 6 mins, 15 s)
        if "Weighted Frobenius" in line:
            capMatrixCompleted = 1

        if "Total allocated memory" in line:
            mbytes = int(line.split()[3]) / 1000

        if "Total time" in line:
            secs = int(line.split()[2].split("s")[0].split(".")[0])

        if dimension > 0:
            capMatrixCompleted = 0
            rows.append(line)
            dimension = dimension - 1
            if dimension == 0:
                iteration.append(rows)
            continue

    warning = ""
    if line_cnt == 0:
        warning = "Warning: Empty File " + in_file
        emptyFP.write(in_file + "\n")
        return [0, line_cnt, warning]

    if len(iteration) == 0:
        # warning= 'Warning: No Cap Matrix in File ' + in_file
        warning = "Warning: No Cap Matrix in File " + full_pattern_file
        warnFP.write(warning + "\n")
        return [0, line_cnt, warning]

    if dbg > 2:
        print("last iteration:")
        print(iteration)

    warning1 = ""
    warning = ""
    if capMatrixCompleted > 0:
        lastIterationIndex = len(iteration) - 1
    else:
        if dbg > 0:
            print("Warning -- iterations= ", iterCnt, len(iteration))
            print(iteration[lastIterationIndex])

        # Newer FasterCap logs (e.g. with -r/GMRES traces) can miss "Weighted Frobenius"
        # while still printing a valid final capacitance matrix. In that case, keep the
        # last parsed matrix instead of dropping the case.
        warning1 = "Missing completion marker; fallback to last matrix " + full_pattern_file
        warnFP.write(warning1 + "\n")
        warning = "FallbackLastMatrix"
        lastIterationIndex = len(iteration) - 1

    matrix_rows = iteration[lastIterationIndex]
    names, mat = matrix_rows_to_float(matrix_rows)
    if quality_gate is not None:
        GateConfig, evaluate_matrix_quality_gate = _load_quality_gate()
        if isinstance(quality_gate, dict):
            gate_cfg = GateConfig(**quality_gate)
        else:
            gate_cfg = quality_gate
        passed, reason, metrics = evaluate_matrix_quality_gate(mat, gate_cfg)
        if not passed:
            rel = metrics.get("global_max_rel_asym", "")
            msg = f"SkippedQuality {reason} rel={rel} " + full_pattern_file
            if skip_qualityFP is not None:
                skip_qualityFP.write(f"{in_file}\t{reason}\t{rel}\n")
            warnFP.write(msg + "\n")
            return [0, line_cnt, msg]

    if symmetrize_avg:
        symmetrize_off_diagonal_avg(mat)
        iteration[lastIterationIndex] = float_matrix_to_rows(names, mat)

    wireCnt = getWireCnt(iteration[0], mets, dbg)
    met = mets[0]

    # parse last complete capacitance matrix
    initCapRowIndex = 0
    ii = 0
    for row in iteration[lastIterationIndex]:
        ii = ii + 1
        # print(row)
        caps = parseMatrixRow(row, met, ii, wireCnt[0], wireCnt[1])
        if len(caps) == 0:
            continue
        if dbg > 0:
            print("Caps = ", caps)

        # Some malformed/partial rows may miss CC2/DiagCC fields.
        # Skip them instead of crashing the whole parse run.
        if len(caps) < 4:
            warnFP.write(
                "SkippedMalformedCaps missing CC2 fields "
                + full_pattern_file
                + " row="
                + row
                + "\n"
            )
            continue

        diagUnder = " Under "
        diagCaps = ""
        if mets[3] > 0:
            diagUnder = " DiagUnder "
            if len(caps) < 5:
                warnFP.write(
                    "SkippedMalformedCaps missing DiagCC field "
                    + full_pattern_file
                    + " row="
                    + row
                    + "\n"
                )
                continue
            if not caps[4]:
                warnFP.write(
                    "SkippedMalformedCaps empty DiagCC list "
                    + full_pattern_file
                    + " row="
                    + row
                    + "\n"
                )
                continue
            dcc = getFF(caps[4][0])
            diagCaps = (
                " DiagDist "
                + str(spacings[1])
                + " DiagWidth "
                + str(widths[1])
                + " DiagCC "
                + dcc
            )

        dist = getWSformat(spacings[0])
        width1 = getWSformat(widths[0])
        out_line = (
            "Metal "
            + str(mets[0])
            + " Over "
            + str(mets[1])
            + diagUnder
            + str(mets[2])
            + "  Dist "
            + dist
            + " Width "
            + width1
        )
        cc = getFF(caps[2])
        fr = getFF(caps[1] - caps[2])
        tc = getFF(caps[1])
        cc2 = getFF(caps[3])
        full_net_name = patternName + "wire_" + str(caps[0])

        # print(out_line, "CC", cc, "FR", fr , 'TC', tc, 'CC2', cc2, ' ', diagCaps, full_net_name, run_stats, warning)
        # Keep LEN as integer multiplier to match OpenRCX parser expectations.
        out_file.write(
            out_line
            + "  LEN "
            + str(len_in_widths)
            + "  CC "
            + cc
            + "  FR "
            + fr
            + "  TC "
            + tc
            + "  CC2 "
            + cc2
            + "  "
            + diagCaps
            + " "
            + full_net_name
        )
        out_file.write("\n")
        if lenMetaFP is not None:
            lenMetaFP.write(
                full_net_name
                + ","
                + str(len_in_widths)
                + ","
                + getWSformat(widths[0])
                + ","
                + getWSformat(physical_len_um)
                + ","
                + "physical_len_um = len_in_widths * width_um"
                + "\n"
            )
    run_stats = (
        str(mbytes)
        + " MB "
        + str(secs)
        + " secs "
        + str(len(iteration))
        + " iterations"
    )
    statsFP.write(run_stats + " " + full_pattern_file + "\n")
    return [1, line_cnt, warning1]


def main():
    arg_parser = argparse.ArgumentParser(description="Parser of a FasterCap file")
    arg_parser.add_argument(
        "-in_list_file",
        type=str,
        default="",
        help="Input Filename with list of input file paths, default= ",
    )
    arg_parser.add_argument(
        "-in_file",
        type=str,
        default="wires.log",
        help="Input Filename, default=wires.log",
    )
    arg_parser.add_argument(
        "-out_file",
        type=str,
        default="pattern.caps",
        help="Output Filename, default=pattern.caps",
    )
    arg_parser.add_argument(
        "-len_meta_file",
        type=str,
        default="pattern.len_meta.csv",
        help="Output csv for LEN multiplier and physical length, default=pattern.len_meta.csv",
    )
    arg_parser.add_argument(
        "-wire", type=int, default=3, help="target wire number, default=3"
    )
    arg_parser.add_argument("-dbg", type=int, default=0, help="debug level, default=0")
    arg_parser.add_argument(
        "--symmetrize-avg",
        action="store_true",
        help="Symmetrize off-diagonal Cij/Cji by arithmetic mean before extraction",
    )
    arg_parser.add_argument(
        "--max-asym-rel",
        type=float,
        default=None,
        help="Skip pattern when full-matrix reciprocity exceeds this (default: disabled)",
    )
    arg_parser.add_argument(
        "--asym-min-cap",
        type=float,
        default=1e-16,
        help="Minimum |C| (F) for reciprocity check on off-diagonal pairs",
    )
    arg_parser.add_argument(
        "--reject-pos-offdiag",
        action="store_true",
        help="Skip pattern when strong off-diagonal entries are positive",
    )
    arg_parser.add_argument(
        "--reject-sign-flip",
        action="store_true",
        help="Skip pattern when strong reciprocal pairs have opposite signs",
    )
    arg_parser.add_argument(
        "--skip-quality-log",
        type=str,
        default="",
        help="TSV log of skipped patterns: path rel reason max_rel",
    )
    arg_parser.add_argument(
        "--skip-quality-append",
        action="store_true",
        help="Append to --skip-quality-log instead of truncating",
    )

    args = arg_parser.parse_args()

    GateConfig, _evaluate_matrix_quality_gate = _load_quality_gate()
    quality_gate = None
    if (
        args.max_asym_rel is not None
        or args.reject_pos_offdiag
        or args.reject_sign_flip
    ):
        reciprocity_cap = (
            args.max_asym_rel if args.max_asym_rel is not None else float("inf")
        )
        quality_gate = GateConfig(
            max_rel=reciprocity_cap,
            min_abs=args.asym_min_cap,
            reject_pos_offdiag=args.reject_pos_offdiag,
            reject_sign_flip=args.reject_sign_flip,
        )

    outFP = OpenFile(args.out_file, "w")
    warnFP = OpenFile("warnings", "w")
    emptyFP = OpenFile("empty_files", "w")
    skip_qualityFP = None
    if args.skip_quality_log:
        mode = "a" if args.skip_quality_append else "w"
        skip_qualityFP = open(args.skip_quality_log, mode, encoding="utf-8")
        if mode == "w":
            skip_qualityFP.write("path\treason\tglobal_max_rel_asym\n")
    elif quality_gate is not None:
        skip_qualityFP = OpenFile("skipped_quality.tsv", "w")
        skip_qualityFP.write("path\treason\tglobal_max_rel_asym\n")
    statsFP = OpenFile("run_stats", "w")
    lenMetaFP = OpenFile(args.len_meta_file, "w")
    lenMetaFP.write(
        "full_net_name,len_in_widths,width_um,physical_len_um,formula\n"
    )
    file_cnt = 0
    incompleteCnt = 0
    empty_file_cnt = 0
    successCnt = 0
    skipped_quality_cnt = 0

    dbg = args.dbg
    parse_kw = dict(
        symmetrize_avg=args.symmetrize_avg,
        quality_gate=quality_gate,
        skip_qualityFP=skip_qualityFP,
    )

    # Single file
    if len(args.in_list_file) == 0:
        retCode = readFasterCapOutPutLog(
            args.in_file,
            outFP,
            warnFP,
            emptyFP,
            statsFP,
            dbg,
            lenMetaFP,
            **parse_kw,
        )
        file_cnt += 1

        if retCode[0] == 1:
            successCnt += 1
            if "Incomplete" in retCode[2]:
                incompleteCnt += 1

        if retCode[0] == 0 and "Empty" in retCode[2]:
            empty_file_cnt += 1
        if retCode[0] == 0 and "Incomplete" in retCode[2]:
            incompleteCnt += 1
        exit()

    # list of files
    f = OpenFile(args.in_list_file)
    for file_line in f:
        retCode = readFasterCapOutPutLog(
            file_line.split()[0],
            outFP,
            warnFP,
            emptyFP,
            statsFP,
            dbg,
            lenMetaFP,
            **parse_kw,
        )
        file_cnt += 1

        if retCode[0] == 1:
            successCnt += 1
            if "Incomplete" in retCode[2]:
                incompleteCnt += 1

        if retCode[0] == 0 and "Empty" in retCode[2]:
            empty_file_cnt += 1
        if retCode[0] == 0 and "Incomplete" in retCode[2]:
            incompleteCnt += 1
        if retCode[0] == 0 and "SkippedQuality" in retCode[2]:
            skipped_quality_cnt += 1

    outFP.close()
    warnFP.close()
    emptyFP.close()
    if skip_qualityFP is not None:
        skip_qualityFP.close()
    statsFP.close()
    lenMetaFP.close()

    print(file_cnt, " Files Parsed")
    print(successCnt, " Files extracted to caps")
    print(empty_file_cnt, " Files are Empty -- look at file:empty_files")
    print(skipped_quality_cnt, " Files skipped for quality -- see skipped_quality.tsv")
    print(incompleteCnt, " Files were incomplete -- look at file: warnings")


if __name__ == "__main__":
    main()

# Dimension 7 x 7
# g1_wire_M3_w0  6.9136e-16 -5.40629e-17 -1.68603e-16 -1.02291e-16 -9.64771e-17 -1.05795e-16 -1.6943e-16
# g2_wire_M5_w0  -7.3632e-17 2.82679e-16 -1.01845e-16 -5.93445e-17 -5.83917e-17 -5.96175e-17 -1.01798e-16
# g3_wire_M4_w1  -1.41823e-16 -2.30241e-17 5.5345e-16 -2.76143e-16 -3.19856e-18 1.15872e-18 -2.70547e-20
# g4_wire_M4_w2  -9.1805e-17 -1.36862e-17 -2.73845e-16 7.20986e-16 -2.7526e-16 -4.54052e-18 1.38176e-18
# g5_wire_M4_w3  -9.05258e-17 -1.32927e-17 -3.24811e-18 -2.75761e-16 7.2318e-16 -2.80613e-16 -3.72233e-18
# g6_wire_M4_w4  -9.13211e-17 -1.37111e-17 1.56117e-18 -4.38767e-18 -2.81118e-16 7.2663e-16 -2.7262e-16
# g7_wire_M4_w5  -1.4171e-16 -2.30185e-17 -3.0492e-20 8.26274e-19 -5.05703e-18 -2.73595e-16 5.535e-16

# Solve statistics:
# Total allocated memory: 4950569 kilobytes
# Total time: 2578.236084s (0 days, 0 hours, 42 mins, 58 s)
