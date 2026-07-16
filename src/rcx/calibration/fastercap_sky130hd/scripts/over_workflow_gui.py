#!/usr/bin/env python3
"""Tkinter dashboard for SKY130 multi-family ICT FasterCap workflows."""

from __future__ import annotations

import os
import queue
import signal
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk


SCRIPT_DIR = Path(__file__).resolve().parent
FC_DIR = SCRIPT_DIR.parent
WORKFLOW = SCRIPT_DIR / "run_family_workflow.sh"

FAMILIES = {
    "Over5": ("Over", "over"),
    "Under5": ("Under", "under"),
    "OverUnder5": ("OverUnder", "overunder"),
    "UnderDiag5": ("DiagUnder", "diagunder"),
}

STAGES = [
    ("setup", "1. 环境与输入"),
    ("process_ict", "2. ICT Process"),
    ("generate_patterns", "3. 生成 Patterns"),
    ("source_geometry", "4. 5-Wire 对称性"),
    ("converter_overlap", "5. Converter / 介质检查"),
    ("fastercap", "6. FasterCap"),
    ("solver_completeness", "7. 结果完整性"),
    ("matrix_quality", "8. 矩阵质量"),
    ("parse", "9. Parse"),
    ("compare", "10. Compare / Plot"),
    ("error_analysis", "11. Golden Rules / Error"),
    ("complete", "12. 汇总报告"),
]

# Combobox labels for WORKFLOW_FROM (empty = run from the beginning).
FROM_CHOICES = [("（从头开始）", "")] + [(title, key) for key, title in STAGES]
FROM_LABEL_BY_KEY = {key: label for label, key in FROM_CHOICES}
FROM_KEY_BY_LABEL = {label: key for label, key in FROM_CHOICES}

COLORS = {
    "PENDING": ("#6b7280", "#ffffff"),
    "RUNNING": ("#d97706", "#ffffff"),
    "WARN": ("#ca8a04", "#ffffff"),
    "PASS": ("#15803d", "#ffffff"),
    "SKIP": ("#15803d", "#ffffff"),
    "FAIL": ("#b91c1c", "#ffffff"),
}

STAGE_LOGS = {
    "process_ict": "process_ict.log",
    "generate_patterns": "generate_patterns.log",
    "source_geometry": "source_geometry.log",
    "converter_overlap": "converter_overlap_precheck.log",
    "fastercap": "fastercap.log",
    "matrix_quality": "matrix_quality.log",
    "parse": "parse_sym0.5",
    "compare": "compare_rules",
    "error_analysis": "error_analysis.log",
}


class WorkflowGui:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("SKY130 Multi-Family FasterCap Workflow")
        self.root.geometry("1180x820")
        self.root.minsize(980, 700)

        self.process: subprocess.Popen[str] | None = None
        self.batch_running = False
        self.output_queue: queue.Queue[str] = queue.Queue()
        self.stage_labels: dict[str, tk.Label] = {}
        self.stage_details: dict[str, tk.StringVar] = {}
        self.last_stage_status: dict[str, tuple[str, str]] = {}
        self.stop_requested = False
        self.active_family = "Over5"
        self.display_family_var = tk.StringVar(value="Over5")
        self.family_status_vars = {
            family: tk.StringVar(value="PENDING") for family in FAMILIES
        }
        self.family_vars = {
            family: tk.BooleanVar(value=True) for family in FAMILIES
        }

        self.len_var = tk.StringVar(value="20")
        self.run_dir_var = tk.StringVar(value="6v2_typ_ict_len20")
        self.stack_var = tk.StringVar(value="")
        self.ict_file_var = tk.StringVar(value=str(FC_DIR / "data/ict/sky130.ict"))
        self.use_no_ict_var = tk.BooleanVar(value=False)
        self.diag_cg_mode_var = tk.StringVar(value="full")
        self.w_list_var = tk.StringVar(value="1")
        self.s_list_var = tk.StringVar(value="1.0 1.5 2.0 3 5 6 7 8 9 10")
        self.max_asym_var = tk.StringVar(value="0.10")
        self.faster_cap_profile_var = tk.StringVar(value="default")
        self.fc_time_limit_var = tk.StringVar(value="1800")
        self.regenerate_var = tk.BooleanVar(value=False)
        self.force_solver_var = tk.BooleanVar(value=False)
        self.strict_var = tk.BooleanVar(value=False)
        self.skip_preflight_var = tk.BooleanVar(value=True)
        self.skip_solver_var = tk.BooleanVar(value=True)
        self.report_dir_var = tk.StringVar(value="workflow_6v2_typ_ict_len20")
        self.overall_var = tk.StringVar(value="未运行")
        self.progress_var = tk.StringVar(value="")
        self.workflow_from_var = tk.StringVar(value=FROM_CHOICES[0][0])

        self._build_ui()
        self.len_var.trace_add("write", self._sync_default_names)
        self.use_no_ict_var.trace_add("write", self._on_process_mode_change)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(250, self._poll)

    @property
    def report_dir(self) -> Path:
        value = self.report_dir_var.get().strip()
        path = Path(value or f"workflow_{self.run_dir_var.get().strip()}")
        base = path if path.is_absolute() else FC_DIR / path
        return base / FAMILIES[self.active_family][1]

    @property
    def report_base(self) -> Path:
        value = self.report_dir_var.get().strip()
        path = Path(value or f"workflow_{self.run_dir_var.get().strip()}")
        return path if path.is_absolute() else FC_DIR / path

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill=tk.BOTH, expand=True)

        config = ttk.LabelFrame(outer, text="运行参数", padding=8)
        config.pack(fill=tk.X)
        fields = [
            ("LEN", self.len_var, 8),
            ("RUN_DIR", self.run_dir_var, 28),
            ("STACK（空=全部；DiagUnder 忽略）", self.stack_var, 22),
            ("W_LIST", self.w_list_var, 12),
            ("MAX_ASYM_REL", self.max_asym_var, 10),
        ]
        for column, (label, variable, width) in enumerate(fields):
            ttk.Label(config, text=label).grid(row=0, column=column, sticky="w", padx=4)
            ttk.Entry(config, textvariable=variable, width=width).grid(
                row=1, column=column, sticky="ew", padx=4
            )
        ttk.Label(config, text="S_LIST").grid(row=2, column=0, sticky="w", padx=4, pady=(8, 0))
        ttk.Entry(config, textvariable=self.s_list_var).grid(
            row=3, column=0, columnspan=5, sticky="ew", padx=4
        )
        ttk.Label(config, text="REPORT_DIR").grid(
            row=2, column=5, sticky="w", padx=4, pady=(8, 0)
        )
        ttk.Entry(config, textvariable=self.report_dir_var, width=34).grid(
            row=3, column=5, sticky="ew", padx=4
        )
        config.columnconfigure(1, weight=1)
        config.columnconfigure(5, weight=1)

        ttk.Label(config, text="ICT_FILE").grid(
            row=4, column=0, sticky="w", padx=4, pady=(8, 0)
        )
        self.ict_file_entry = ttk.Entry(config, textvariable=self.ict_file_var)
        self.ict_file_entry.grid(row=5, column=0, columnspan=5, sticky="ew", padx=4)
        ttk.Checkbutton(
            config,
            text="无 ICT（built-in stack，TECH LEF + SKY130_BOTTOM_Z）",
            variable=self.use_no_ict_var,
            command=self._on_process_mode_change,
        ).grid(row=6, column=0, columnspan=5, sticky="w", padx=4, pady=(4, 0))
        ttk.Label(config, text="DiagUnder CG").grid(
            row=4, column=5, sticky="w", padx=4, pady=(8, 0)
        )
        ttk.Combobox(
            config,
            textvariable=self.diag_cg_mode_var,
            values=("full", "c"),
            state="readonly",
            width=12,
        ).grid(row=5, column=5, sticky="w", padx=4)
        ttk.Label(config, text="FasterCap profile / TIME_LIMIT(s)").grid(
            row=6, column=5, sticky="w", padx=4, pady=(8, 0)
        )
        fc_opts = ttk.Frame(config)
        fc_opts.grid(row=7, column=5, sticky="w", padx=4)
        ttk.Combobox(
            fc_opts,
            textvariable=self.faster_cap_profile_var,
            values=("default", "optimized"),
            state="readonly",
            width=12,
        ).pack(side=tk.LEFT)
        ttk.Entry(
            fc_opts,
            textvariable=self.fc_time_limit_var,
            width=8,
        ).pack(side=tk.LEFT, padx=(8, 0))

        family_options = ttk.Frame(config)
        family_options.grid(row=8, column=0, columnspan=6, sticky="ew", pady=(8, 0))
        ttk.Label(family_options, text="Patterns:").pack(side=tk.LEFT, padx=5)
        for family, (label, _slug) in FAMILIES.items():
            ttk.Checkbutton(
                family_options,
                text=label,
                variable=self.family_vars[family],
            ).pack(side=tk.LEFT, padx=5)
            ttk.Label(
                family_options,
                textvariable=self.family_status_vars[family],
                width=9,
            ).pack(side=tk.LEFT, padx=(0, 8))

        options = ttk.Frame(config)
        options.grid(row=9, column=0, columnspan=6, sticky="ew", pady=(8, 0))
        ttk.Checkbutton(
            options,
            text="重新生成 patterns（会覆盖已有 wires.log）",
            variable=self.regenerate_var,
        ).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(
            options,
            text="强制重跑 FasterCap（忽略已有 wires.log）",
            variable=self.force_solver_var,
        ).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(options, text="矩阵质量 Fail-Fast", variable=self.strict_var).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Checkbutton(
            options,
            text="隔离 converter high/error 后继续",
            variable=self.skip_preflight_var,
        ).pack(side=tk.LEFT, padx=5)
        ttk.Checkbutton(
            options,
            text="隔离 FasterCap 运行失败后继续",
            variable=self.skip_solver_var,
        ).pack(side=tk.LEFT, padx=5)
        self.start_button = ttk.Button(options, text="开始运行", command=self.start)
        self.start_button.pack(side=tk.RIGHT, padx=5)
        self.stop_button = ttk.Button(options, text="停止", command=self.stop, state=tk.DISABLED)
        self.stop_button.pack(side=tk.RIGHT, padx=5)
        ttk.Button(options, text="载入当前状态", command=self.refresh_status).pack(
            side=tk.RIGHT, padx=5
        )
        ttk.Button(options, text="打开输出目录", command=self.open_report_dir).pack(
            side=tk.RIGHT, padx=5
        )

        main = ttk.Panedwindow(outer, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        left = ttk.LabelFrame(main, text="Workflow Stages", padding=8)
        right = ttk.Panedwindow(main, orient=tk.VERTICAL)
        main.add(left, weight=2)
        main.add(right, weight=5)

        header = ttk.Frame(left)
        header.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(header, text="总体状态：").pack(side=tk.LEFT)
        ttk.Label(header, textvariable=self.overall_var, font=("", 11, "bold")).pack(
            side=tk.LEFT
        )
        ttk.Label(header, text="FasterCap：").pack(side=tk.LEFT, padx=(12, 2))
        ttk.Label(
            header,
            textvariable=self.progress_var,
            font=("", 11, "bold"),
            foreground="#1d4ed8",
        ).pack(side=tk.LEFT)
        ttk.Label(header, text="查看：").pack(side=tk.LEFT, padx=(12, 2))
        family_view = ttk.Combobox(
            header,
            textvariable=self.display_family_var,
            values=tuple(FAMILIES),
            state="readonly",
            width=15,
        )
        family_view.pack(side=tk.LEFT)
        family_view.bind("<<ComboboxSelected>>", self._select_report_family)

        for stage, title in STAGES:
            row = ttk.Frame(left)
            row.pack(fill=tk.X, pady=3)
            label = tk.Label(
                row,
                text=title,
                width=24,
                anchor="w",
                padx=8,
                pady=7,
                bg=COLORS["PENDING"][0],
                fg=COLORS["PENDING"][1],
            )
            label.pack(side=tk.LEFT, fill=tk.X, expand=True)
            detail = tk.StringVar(value="PENDING")
            ttk.Label(row, textvariable=detail, width=18).pack(side=tk.LEFT, padx=5)
            ttk.Button(
                row,
                text="从此开始",
                width=8,
                command=lambda selected=stage: self.start_from_stage(selected),
            ).pack(side=tk.RIGHT, padx=(0, 2))
            ttk.Button(
                row,
                text="Debug",
                width=7,
                command=lambda selected=stage: self.show_stage_log(selected),
            ).pack(side=tk.RIGHT)
            self.stage_labels[stage] = label
            self.stage_details[stage] = detail

        from_row = ttk.Frame(left)
        from_row.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(from_row, text="从步骤开始：").pack(side=tk.LEFT)
        from_box = ttk.Combobox(
            from_row,
            textvariable=self.workflow_from_var,
            values=tuple(label for label, _key in FROM_CHOICES),
            state="readonly",
            width=28,
        )
        from_box.pack(side=tk.LEFT, padx=4)
        ttk.Label(
            from_row,
            text="（跳过 FasterCap → 选 8/9）",
            foreground="#6b7280",
        ).pack(side=tk.LEFT, padx=4)

        log_frame = ttk.LabelFrame(right, text="实时日志 / Debug", padding=5)
        output_frame = ttk.LabelFrame(right, text="输出文件位置", padding=5)
        right.add(log_frame, weight=4)
        right.add(output_frame, weight=2)

        self.log_text = scrolledtext.ScrolledText(
            log_frame, wrap=tk.NONE, height=22, font=("monospace", 9)
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self.output_text = scrolledtext.ScrolledText(
            output_frame, wrap=tk.NONE, height=10, font=("monospace", 9)
        )
        self.output_text.pack(fill=tk.BOTH, expand=True)
        self._refresh_output_paths()

    def _process_name_prefix(self) -> str:
        return "6v2_typ_no_ict_len" if self.use_no_ict_var.get() else "6v2_typ_ict_len"

    def _on_process_mode_change(self, *_args: object) -> None:
        use_no_ict = self.use_no_ict_var.get()
        state = "disabled" if use_no_ict else "normal"
        self.ict_file_entry.configure(state=state)
        self._sync_default_names()

    def _sync_default_names(self, *_args: object) -> None:
        value = self.len_var.get().strip()
        if value.isdigit():
            prefix = self._process_name_prefix()
            self.run_dir_var.set(f"{prefix}{value}")
            self.report_dir_var.set(f"workflow_{prefix}{value}")
            self._refresh_output_paths()

    def _set_stage(self, stage: str, status: str, detail: str) -> None:
        normalized = status if status in COLORS else "PENDING"
        background, foreground = COLORS[normalized]
        self.stage_labels[stage].configure(bg=background, fg=foreground)
        display = normalized if not detail else f"{normalized}: {detail}"
        self.stage_details[stage].set(display[:80])

    def _select_report_family(self, _event: object | None = None) -> None:
        self.active_family = self.display_family_var.get()
        self._reset_stages()
        self.refresh_status()

    def _reset_stages(self) -> None:
        self.last_stage_status.clear()
        for stage, _ in STAGES:
            self._set_stage(stage, "PENDING", "")
        self.overall_var.set("运行中")

    def _environment(self) -> dict[str, str]:
        env = os.environ.copy()
        use_no_ict = self.use_no_ict_var.get()
        values: dict[str, str] = {
            "LEN": self.len_var.get().strip(),
            "RUN_DIR": self.run_dir_var.get().strip(),
            "REPORT_DIR": str(self.report_dir),
            "STACK": self.stack_var.get().strip(),
            "ICT_FILE": "" if use_no_ict else self.ict_file_var.get().strip(),
            "DIAG_CG_MODE": self.diag_cg_mode_var.get().strip(),
            "CG_MODE": "a",
            "W_LIST": self.w_list_var.get().strip(),
            "S_LIST": self.s_list_var.get().strip(),
            "MAX_ASYM_REL": self.max_asym_var.get().strip(),
            "FASTER_CAP_PROFILE": self.faster_cap_profile_var.get().strip(),
            "FASTER_CAP_TIME_LIMIT": self.fc_time_limit_var.get().strip(),
            "REJECT_POS_OFFDIAG": "1",
            "REJECT_SIGN_FLIP": "1",
            "PARSE_STACK_DELAY": os.environ.get("PARSE_STACK_DELAY", "0.25"),
            "MPLBACKEND": "Agg",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
            "REGENERATE": "1" if self.regenerate_var.get() else "0",
            "FORCE_SOLVER": "1" if self.force_solver_var.get() else "0",
            "STRICT_POSTCHECK": "1" if self.strict_var.get() else "0",
            "SKIP_PREFLIGHT_FAILURES": (
                "1" if self.skip_preflight_var.get() else "0"
            ),
            "SKIP_SOLVER_FAILURES": "1" if self.skip_solver_var.get() else "0",
        }
        from_key = FROM_KEY_BY_LABEL.get(self.workflow_from_var.get().strip(), "")
        if from_key:
            values["WORKFLOW_FROM"] = from_key
        else:
            values["WORKFLOW_FROM"] = ""
        if use_no_ict:
            values["GEN_DIR"] = str(FC_DIR / "data/generated/sky130hs_6m_no_ict")
        env.update(values)
        return env

    def start_from_stage(self, stage: str) -> None:
        label = FROM_LABEL_BY_KEY.get(stage)
        if not label:
            messagebox.showerror("参数错误", f"未知步骤: {stage}")
            return
        self.workflow_from_var.set(label)
        # Partial FasterCap runs: avoid regenerating patterns / forcing FC.
        if stage in {
            "solver_completeness",
            "matrix_quality",
            "parse",
            "compare",
            "error_analysis",
            "complete",
        }:
            self.regenerate_var.set(False)
            self.force_solver_var.set(False)
        self.start()

    def start(self) -> None:
        if self.process and self.process.poll() is None:
            messagebox.showwarning("正在运行", "已有 workflow 正在运行。")
            return
        families = [
            family for family in FAMILIES if self.family_vars[family].get()
        ]
        if not families:
            messagebox.showerror("参数错误", "至少选择一个 pattern family。")
            return
        if len(families) > 1 and self.stack_var.get().strip():
            messagebox.showerror(
                "参数错误",
                "多 family 批量运行时 STACK 必须留空；stack 名称只属于一个 family。",
            )
            return
        if not self.len_var.get().strip().isdigit():
            messagebox.showerror("参数错误", "LEN 必须是正整数。")
            return
        time_limit = self.fc_time_limit_var.get().strip()
        if not time_limit.isdigit() or int(time_limit) <= 0:
            messagebox.showerror("参数错误", "FasterCap TIME_LIMIT 必须是正整数（秒）。")
            return
        if not self.use_no_ict_var.get() and not Path(
            self.ict_file_var.get().strip()
        ).is_file():
            messagebox.showerror("缺少 ICT", self.ict_file_var.get().strip())
            return
        if not WORKFLOW.is_file():
            messagebox.showerror("缺少脚本", str(WORKFLOW))
            return

        self.report_base.mkdir(parents=True, exist_ok=True)
        self.log_text.delete("1.0", tk.END)
        self.stop_requested = False
        self.batch_running = True
        self.progress_var.set("")
        from_key = FROM_KEY_BY_LABEL.get(self.workflow_from_var.get().strip(), "")
        if from_key:
            self.log_text.insert(
                tk.END,
                f"WORKFLOW_FROM={from_key} "
                f"（从 {self.workflow_from_var.get()} 开始，跳过更早步骤）\n",
            )
        self.active_family = families[0]
        for family, variable in self.family_status_vars.items():
            variable.set("QUEUED" if family in families else "SKIP")
        self._reset_stages()
        self._refresh_output_paths()
        self.start_button.configure(state=tk.DISABLED)
        self.stop_button.configure(state=tk.NORMAL)

        threading.Thread(
            target=self._run_batch,
            args=(families, self._environment(), self.report_base),
            daemon=True,
        ).start()

    def _run_batch(
        self,
        families: list[str],
        base_env: dict[str, str],
        report_base: Path,
    ) -> None:
        failed = False
        for index, family in enumerate(families):
            if self.stop_requested:
                break
            slug = FAMILIES[family][1]
            env = base_env.copy()
            env.update(
                {
                    "FAMILY": family,
                    "REPORT_DIR": str(report_base / slug),
                    "PREPARE_ICT": "1" if index == 0 else "0",
                    "REGENERATE": (
                        base_env["REGENERATE"] if index == 0 else "0"
                    ),
                }
            )
            self.output_queue.put(f"@@FAMILY_START@@{family}\n")
            try:
                self.process = subprocess.Popen(
                    [str(WORKFLOW)],
                    cwd=FC_DIR,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    start_new_session=True,
                )
            except OSError as error:
                failed = True
                self.output_queue.put(f"启动失败: {error}\n")
                self.output_queue.put(f"@@FAMILY_DONE@@{family}:FAIL\n")
                continue
            if self.process.stdout:
                for line in self.process.stdout:
                    self.output_queue.put(line)
            return_code = self.process.wait()
            status = "PASS" if return_code == 0 else "FAIL"
            failed = failed or return_code != 0
            self.output_queue.put(f"@@FAMILY_DONE@@{family}:{status}\n")
        final = "STOPPED" if self.stop_requested else ("FAIL" if failed else "PASS")
        self.output_queue.put(f"@@BATCH_DONE@@{final}\n")

    def stop(self) -> None:
        if not self.process or self.process.poll() is not None:
            return
        if messagebox.askyesno("停止 workflow", "确定终止当前 workflow？"):
            self.stop_requested = True
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def refresh_status(self) -> None:
        status_path = self.report_dir / "stage_status.tsv"
        if status_path.is_file():
            latest: dict[str, tuple[str, str]] = {}
            for line in status_path.read_text(errors="replace").splitlines():
                parts = line.split("\t", 2)
                if len(parts) == 3:
                    latest[parts[0]] = (parts[1], parts[2])
            for stage, (status, detail) in latest.items():
                if stage in self.stage_labels:
                    self._set_stage(stage, status, detail)
            self.last_stage_status = latest

        summary = self.report_dir / "summary.md"
        running = self.batch_running
        if running:
            self.overall_var.set("运行中")
        else:
            batch_summary = self.report_base / "summary.md"
            status_source = batch_summary if batch_summary.is_file() else summary
            text = status_source.read_text(errors="replace") if status_source.is_file() else ""
            if "Overall status: **PASS**" in text:
                self.overall_var.set("PASS")
            elif "Overall status: **FAIL**" in text:
                self.overall_var.set("FAIL")
        self._refresh_output_paths()

    def _refresh_output_paths(self) -> None:
        report = self.report_dir
        paths = [
            ("Run directory", FC_DIR / self.run_dir_var.get().strip()),
            ("Batch summary", self.report_base / "summary.md"),
            ("Workflow summary", report / "summary.md"),
            ("Stage status", report / "stage_status.tsv"),
            ("Source geometry", report / "source_geometry.csv"),
            ("Converter / overlap", report / "converter_overlap_precheck.csv"),
            ("Solver completeness", report / "solver_completeness.csv"),
            ("FasterCap progress", report / "fastercap_progress.txt"),
            ("Matrix symmetry", report / "symmetry_summary.txt"),
            ("Matrix details", report / "symmetry_full.csv"),
            ("Parse outputs", report / f"parse_sym{self.max_asym_var.get().strip()}"),
            ("Per-pattern plots", report / "compare_rules"),
            ("Error analysis", report / "error_analysis"),
        ]
        self.output_text.delete("1.0", tk.END)
        for label, path in paths:
            marker = "✓" if path.exists() else "·"
            self.output_text.insert(tk.END, f"{marker} {label}: {path}\n")

    def show_stage_log(self, stage: str) -> None:
        relative = STAGE_LOGS.get(stage)
        if not relative:
            self.log_text.insert(tk.END, f"\n[{stage}] 没有独立日志文件。\n")
            return
        path = self.report_dir / relative
        self.log_text.insert(tk.END, f"\n--- {stage}: {path} ---\n")
        if path.is_dir():
            entries = sorted(path.iterdir())
            self.log_text.insert(
                tk.END, "\n".join(str(entry) for entry in entries[:200]) + "\n"
            )
        elif path.is_file():
            text = path.read_text(errors="replace")
            self.log_text.insert(tk.END, text[-100_000:])
            if text and not text.endswith("\n"):
                self.log_text.insert(tk.END, "\n")
        else:
            self.log_text.insert(tk.END, "尚未生成。\n")
        self.log_text.see(tk.END)

    def open_report_dir(self) -> None:
        self.report_base.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.Popen(["xdg-open", str(self.report_base)])
        except OSError as error:
            messagebox.showerror("无法打开目录", str(error))

    def _poll(self) -> None:
        while True:
            try:
                line = self.output_queue.get_nowait()
            except queue.Empty:
                break
            if line.startswith("@@FAMILY_START@@"):
                family = line.strip().split("@@", 2)[-1]
                self.active_family = family
                self.display_family_var.set(family)
                self.family_status_vars[family].set("RUNNING")
                self.progress_var.set("")
                self._reset_stages()
                self._refresh_output_paths()
                self.log_text.insert(
                    tk.END, f"\n=== {FAMILIES[family][0]} workflow ===\n"
                )
                continue
            if line.startswith("@@FAMILY_DONE@@"):
                payload = line.strip().split("@@", 2)[-1]
                family, status = payload.split(":", 1)
                self.family_status_vars[family].set(status)
                continue
            if line.startswith("@@BATCH_DONE@@"):
                status = line.strip().split("@@", 2)[-1]
                self.batch_running = False
                self.overall_var.set(status)
                self.start_button.configure(state=tk.NORMAL)
                self.stop_button.configure(state=tk.DISABLED)
                self._write_batch_summary(status)
                continue
            if line.startswith("[PROGRESS]"):
                detail = line.strip()[len("[PROGRESS]") :].strip()
                # Prefer compact N/M in the header (e.g. 48/200).
                parts = detail.split(None, 2)
                if len(parts) >= 1 and "/" in parts[0]:
                    self.progress_var.set(parts[0] if len(parts) == 1 else f"{parts[0]} {parts[1]}")
                else:
                    self.progress_var.set(detail[:40])
                if "fastercap" in self.stage_labels:
                    self._set_stage("fastercap", "RUNNING", detail[:60])
                self.log_text.insert(tk.END, line)
                self.log_text.see(tk.END)
                continue
            self.log_text.insert(tk.END, line)
            self.log_text.see(tk.END)

        self.refresh_status()
        if not self.batch_running:
            self.start_button.configure(state=tk.NORMAL)
            self.stop_button.configure(state=tk.DISABLED)
        self.root.after(250, self._poll)

    def _write_batch_summary(self, status: str) -> None:
        process_mode = (
            "built-in no-ICT"
            if self.use_no_ict_var.get()
            else f"ICT `{self.ict_file_var.get().strip()}`"
        )
        lines = [
            f"# SKY130 FasterCap batch — L{self.len_var.get().strip()}",
            "",
            f"- Overall status: **{status}**",
            f"- Process: {process_mode}",
            f"- Run directory: `{FC_DIR / self.run_dir_var.get().strip()}`",
            "",
            "| family | status | report |",
            "|--------|--------|--------|",
        ]
        for family, (label, slug) in FAMILIES.items():
            family_status = self.family_status_vars[family].get()
            lines.append(
                f"| {label} | **{family_status}** | "
                f"`{self.report_base / slug / 'summary.md'}` |"
            )
        (self.report_base / "summary.md").write_text("\n".join(lines) + "\n")

    def _on_close(self) -> None:
        if self.batch_running:
            if not messagebox.askyesno("退出", "workflow 仍在运行，终止并退出？"):
                return
            self.stop_requested = True
            try:
                if self.process and self.process.poll() is None:
                    os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    WorkflowGui(root)
    root.mainloop()


if __name__ == "__main__":
    main()
