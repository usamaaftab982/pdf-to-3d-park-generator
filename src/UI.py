import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
import threading
import os
import subprocess
import json
import sys
from pathlib import Path

# ── Import sibling modules 
# Both live in the same directory as this file.
_HERE = Path(__file__).parent
_ROOT = _HERE.parent            # project root, one level up from src/
sys.path.insert(0, str(_HERE))

import pdf_extractor
import ai_enricher

# ── Paths 
BLENDER_SCRIPT = _HERE / "blender_JSON_to_3D.py"
OUT_JSON       = _ROOT / "park_output.json"
OUT_BLEND      = _ROOT / "park_scene.blend"
OUT_IMAGE      = _ROOT / "model_preview.png"

# ── Log tag colours 
TAG_OK   = ("ok",   {"foreground": "#27ae60"})
TAG_WARN = ("warn", {"foreground": "#e67e22"})
TAG_ERR  = ("err",  {"foreground": "#e74c3c"})
TAG_INFO = ("info", {"foreground": "#2980b9"})


class ParkAppUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("PDF → 3D Park Generator")
        self.root.geometry("600x700")
        self.root.resizable(True, True)
        self.root.configure(bg="#f5f5f5")

        # ── macOS fix: native "Aqua" tk.Button ignores bg/fg colors, so we
        # switch to ttk.Button with the "clam" theme, which does respect them.
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass  # clam not available, fall back to platform default

        style.configure("Browse.TButton", background="#3498db",
                        foreground="white", padding=6, borderwidth=0,
                        font=("Arial", 10))
        style.map("Browse.TButton",
                  background=[("active", "#2980b9")])

        style.configure("Run.TButton", background="#27ae60",
                        foreground="white", padding=10,
                        font=("Arial", 11, "bold"), borderwidth=0)
        style.map("Run.TButton",
                  background=[("active", "#1e8449"), ("disabled", "#95a5a6")])


        # ── State 
        self.pdf_path     = tk.StringVar(value="")
        self.blender_path = tk.StringVar(value=self._detect_blender())
        self.step1_var    = tk.BooleanVar(value=True)
        self.step2_var    = tk.BooleanVar(value=True)
        self.step3_var    = tk.BooleanVar(value=True)
        self.step4_var    = tk.BooleanVar(value=False)

        self._build_ui()

    # ══════════════════════════════════════════════════════════════════════
    # UI construction
    # ══════════════════════════════════════════════════════════════════════

    def _build_ui(self) -> None:
        pad = {"padx": 16, "pady": 4}

        # ── Header 
        hdr = tk.Frame(self.root, bg="#2c3e50", height=52)
        hdr.pack(fill="x")
        tk.Label(hdr, text="PDF → 3D Park Generator",
                 font=("Arial", 14, "bold"),
                 bg="#2c3e50", fg="white").pack(pady=12)

        # ── PDF selection 
        sec = self._section("Input")
        pdf_row = tk.Frame(sec, bg="white")
        pdf_row.pack(fill="x", **pad)

        self.pdf_entry = tk.Entry(pdf_row, textvariable=self.pdf_path,
                                  state="readonly", width=46,
                                  relief="flat", bg="#ecf0f1")
        self.pdf_entry.pack(side="left", expand=True, fill="x", ipady=4)
        ttk.Button(pdf_row, text="Browse…", command=self._browse_pdf,
                   style="Browse.TButton").pack(side="right", padx=(6, 0))

        tk.Label(sec, text="Blender executable:",
                 bg="white", anchor="w").pack(fill="x", **pad)
        tk.Entry(sec, textvariable=self.blender_path,
                 relief="flat", bg="#ecf0f1").pack(fill="x", **pad, ipady=3)

        # ── Steps 
        sec2 = self._section("Pipeline Steps")
        steps = [
            ("Step 1 — Extract PDF data",        self.step1_var, None),
            ("Step 2 — AI material enrichment",  self.step2_var, None),
            ("Step 3 — Generate 3D model",       self.step3_var, self._toggle_step4),
            ("Step 4 — Render & show preview",   self.step4_var, None),
        ]
        self._step4_cb = None
        for label, var, cmd in steps:
            cb = tk.Checkbutton(sec2, text=label, variable=var,
                                bg="white", anchor="w",
                                command=cmd if cmd else None)
            cb.pack(fill="x", padx=24, pady=1)
            if label.startswith("Step 4"):
                self._step4_cb = cb
        self._toggle_step4()

        # ── Progress 
        prog_frame = tk.Frame(self.root, bg="#f5f5f5")
        prog_frame.pack(fill="x", padx=16, pady=(6, 2))
        self.progress_label = tk.Label(prog_frame, text="Ready.",
                                       bg="#f5f5f5", anchor="w",
                                       font=("Arial", 9))
        self.progress_label.pack(side="top", fill="x")
        self.progress_bar = ttk.Progressbar(prog_frame, mode="determinate",
                                            maximum=4)
        self.progress_bar.pack(fill="x")

        # ── Log 
        sec3 = self._section("Log Output")
        self.log_area = scrolledtext.ScrolledText(
            sec3, height=10, state="disabled",
            bg="#1e1e1e", fg="#d4d4d4",
            font=("Courier", 9), relief="flat"
        )
        self.log_area.pack(fill="both", expand=True, padx=8, pady=6)
        for tag, cfg in (TAG_OK, TAG_WARN, TAG_ERR, TAG_INFO):
            self.log_area.tag_config(tag, **cfg)

        # ── Analytics panel 
        sec4 = self._section("Analytics")
        self.analytics_text = tk.Text(sec4, height=5, state="disabled",
                                      bg="#fdfefe", relief="flat",
                                      font=("Courier", 9))
        self.analytics_text.pack(fill="both", expand=True, padx=8, pady=6)

        # ── Run button 
        self.run_btn = ttk.Button(
            self.root, text="▶  RUN PIPELINE",
            style="Run.TButton",
            command=self._start_thread,
        )
        self.run_btn.pack(fill="x", padx=16, pady=(4, 12), ipady=4)

    def _section(self, title: str) -> tk.Frame:
        """Labelled white card section."""
        outer = tk.Frame(self.root, bg="#f5f5f5")
        outer.pack(fill="x", padx=12, pady=4)
        tk.Label(outer, text=title, font=("Arial", 9, "bold"),
                 bg="#f5f5f5", fg="#7f8c8d").pack(anchor="w")
        inner = tk.Frame(outer, bg="white", bd=1, relief="solid")
        inner.pack(fill="x")
        return inner

    # ══════════════════════════════════════════════════════════════════════
    # Helpers
    # ══════════════════════════════════════════════════════════════════════

    @staticmethod
    def _detect_blender() -> str:
        """Try common Blender install paths; return first that exists."""
        candidates = [
            "/Applications/Blender.app/Contents/MacOS/blender",  # macOS
            "/usr/bin/blender",                                    # Linux
            r"C:\Program Files\Blender Foundation\Blender 4.1\blender.exe",
        ]
        for c in candidates:
            if Path(c).exists():
                return c
        return "blender"   # hope it's on PATH

    def _toggle_step4(self) -> None:
        if self._step4_cb is None:
            return
        if self.step3_var.get():
            self._step4_cb.config(state="normal")
        else:
            self.step4_var.set(False)
            self._step4_cb.config(state="disabled")

    def _browse_pdf(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
        if path:
            self.pdf_path.set(path)

    # ── Logging 

    def _log(self, msg: str, tag: str = "info") -> None:
        self.log_area.config(state="normal")
        self.log_area.insert(tk.END, msg + "\n", tag)
        self.log_area.see(tk.END)
        self.log_area.config(state="disabled")

    def _set_progress(self, step: int, label: str) -> None:
        self.progress_bar["value"] = step
        self.progress_label.config(text=label)

    def _update_analytics(self, analytics: dict) -> None:
        """Render the analytics dict into the analytics panel."""
        lines = []
        if "surface_count" in analytics:
            lines.append(
                f"Surfaces: {analytics['surface_count']}  |  "
                f"Vectors: {analytics.get('vector_count', '?')}  |  "
                f"Equipment: {analytics.get('equipment_count', '?')}"
            )
        if "material_breakdown" in analytics:
            lines.append("")
            lines.append("Material Breakdown:")
            for mat, info in analytics["material_breakdown"].items():
                lines.append(
                    f"  {mat:<25}  {info['count']:>3} surface(s)  "
                    f"  area: {info['total_area_px2']:>10,.0f} px²"
                )
        if "enrichment_time_s" in analytics:
            lines.append(
                f"\nAI enrichment: {analytics['enrichment_time_s']} s  "
                f"(model: {analytics.get('model_used', '?')})"
            )

        text = "\n".join(lines) if lines else "No analytics yet."
        self.analytics_text.config(state="normal")
        self.analytics_text.delete("1.0", tk.END)
        self.analytics_text.insert(tk.END, text)
        self.analytics_text.config(state="disabled")

    # ── Show rendered image 

    def _show_image(self, image_path: str) -> None:
        if not Path(image_path).exists():
            self._log("Step 4: Preview image not found.", "warn")
            return
        try:
            win = tk.Toplevel(self.root)
            win.title("Model Preview")
            img = tk.PhotoImage(file=image_path)
            lbl = tk.Label(win, image=img)
            lbl.image = img   # keep reference
            lbl.pack()
        except Exception as e:
            self._log(f"Step 4: Could not display image — {e}", "err")

    # ══════════════════════════════════════════════════════════════════════
    # Pipeline execution
    # ══════════════════════════════════════════════════════════════════════

    def _start_thread(self) -> None:
        pdf = self.pdf_path.get().strip()
        if not pdf:
            messagebox.showerror("Error", "Please select a PDF file first.")
            return
        if not Path(pdf).is_file():
            messagebox.showerror("Error", f"File not found:\n{pdf}")
            return

        self.run_btn.config(state="disabled")
        self.log_area.config(state="normal")
        self.log_area.delete("1.0", tk.END)
        self.log_area.config(state="disabled")
        self.progress_bar["value"] = 0

        threading.Thread(target=self._run_pipeline,
                         args=(pdf,), daemon=True).start()

    def _run_pipeline(self, pdf: str) -> None:
        out_json = str(OUT_JSON)
        analytics_data: dict = {}

        try:
            # ── Step 1 
            if self.step1_var.get():
                self.root.after(0, self._set_progress, 1, "Step 1: Extracting PDF…")
                self._log("── Step 1: Extract PDF Data ──────────────────", "info")
                result = pdf_extractor.extract_pdf(pdf, out_json)
                if result and "analytics" in result:
                    analytics_data.update(result["analytics"])
                    self.root.after(0, self._update_analytics, analytics_data)
                self._log(f"  ✓ Extracted → {out_json}", "ok")

            # ── Step 2 
            if self.step2_var.get():
                self.root.after(0, self._set_progress, 2, "Step 2: AI enrichment…")
                self._log("── Step 2: AI Material Enrichment ────────────", "info")
                enrich_stats = ai_enricher.enrich_surfaces(out_json, out_json)
                if enrich_stats:
                    analytics_data.update(enrich_stats)
                    self.root.after(0, self._update_analytics, analytics_data)
                self._log("  ✓ Enrichment complete.", "ok")

            # ── Step 3 
            if self.step3_var.get():
                self.root.after(0, self._set_progress, 3, "Step 3: Generating 3D model…")
                self._log("── Step 3: Blender 3D Generation ─────────────", "info")

                blender_exe = self.blender_path.get().strip()
                if not blender_exe:
                    raise FileNotFoundError("Blender executable path is empty.")

                cmd = [
                    blender_exe,
                    "--background",
                    "--python", str(BLENDER_SCRIPT),
                    "--",                      # separator: flags below go to our script
                ]
                if self.step4_var.get():
                    cmd.append("--render-preview")

                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=300
                )

                # Echo Blender's stdout (filter noise)
                for line in result.stdout.splitlines():
                    if "[Blender]" in line or "Error" in line:
                        tag = "err" if "Error" in line else "info"
                        self._log(f"  {line}", tag)

                if result.returncode != 0:
                    self._log(f"  ✗ Blender exited {result.returncode}", "err")
                    self._log(result.stderr[-800:], "err")
                else:
                    self._log(f"  ✓ Scene saved → {OUT_BLEND}", "ok")

            # ── Step 4 
            if self.step4_var.get():
                self.root.after(0, self._set_progress, 4, "Step 4: Showing preview…")
                self._log("── Step 4: Display Preview ────────────────────", "info")
                self.root.after(0, self._show_image, str(OUT_IMAGE))

            # ── Load final analytics from JSON 
            if OUT_JSON.exists():
                with open(OUT_JSON, encoding="utf-8") as f:
                    final = json.load(f)
                if "analytics" in final:
                    analytics_data.update(final["analytics"])
                    self.root.after(0, self._update_analytics, analytics_data)

            self.root.after(0, self._set_progress, 4, "Done ✓")
            self._log("══ Pipeline finished successfully. ════════════════", "ok")

        except subprocess.TimeoutExpired:
            self._log("  ✗ Blender timed out (>5 min).", "err")
        except Exception as exc:
            self._log(f"  ✗ CRITICAL ERROR: {exc}", "err")
            import traceback
            self._log(traceback.format_exc(), "err")
        finally:
            self.root.after(0, self.run_btn.config, {"state": "normal"})


# ── Entry point 
if __name__ == "__main__":
    root = tk.Tk()
    app  = ParkAppUI(root)
    root.mainloop()