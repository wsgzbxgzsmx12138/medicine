"""人类可读的运行日志，写入 D:\\zzz。"""

from __future__ import annotations

import os
import traceback
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Any

LOG_DIR = Path(os.getenv("RUN_LOG_DIR", "D:/zzz"))

_current: ContextVar["RunLogger | None"] = ContextVar("run_logger", default=None)


def get_run_logger() -> "RunLogger | None":
    return _current.get()


def _clip(text: str, limit: int = 120) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class RunLogger:
    """每次审核运行一份日志，用大白话记录「在干嘛、怎么想的、用的啥、结果如何」。"""

    def __init__(
        self,
        upload_dir: Path,
        output_dir: Path,
        *,
        use_llm: bool,
        source: str = "未知",
    ) -> None:
        self.upload_dir = Path(upload_dir)
        self.output_dir = Path(output_dir)
        self.use_llm_requested = use_llm
        self.source = source
        self.started = datetime.now()
        self._lines: list[str] = []
        self._current_stage = ""
        self._llm_round = 0
        self._doc_fill_round = 0

        LOG_DIR.mkdir(parents=True, exist_ok=True)
        stamp = self.started.strftime("%Y%m%d_%H%M%S")
        self.log_path = LOG_DIR / f"运行日志_{stamp}.txt"
        self.latest_path = LOG_DIR / "最新运行日志.txt"

    def __enter__(self) -> "RunLogger":
        _current.set(self)
        self._header()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc is not None:
            self.error(f"运行中断：{exc}")
            self.blank()
            self.write("【错误详情】")
            self.write(traceback.format_exc())
        self._flush()
        _current.set(None)

    def write(self, line: str = "") -> None:
        self._lines.append(line)

    def blank(self) -> None:
        self.write("")

    def section(self, title: str, step: str | None = None) -> None:
        self.blank()
        if step:
            self._current_stage = f"{step} · {title}"
            self.write(f"{'═' * 60}")
            self.write(f"【当前阶段】{self._current_stage}")
            self.write(f"{'═' * 60}")
        else:
            self.write(f"{'═' * 60}")
            self.write(title)
            self.write(f"{'═' * 60}")

    def stage_now(self) -> None:
        """在阶段中间再次强调当前进度。"""
        if self._current_stage:
            self.write(f"📍 进度：{self._current_stage}")

    def doing(self, text: str) -> None:
        self.write(f"▶ 正在做什么：{text}")

    def think(self, text: str) -> None:
        self.write(f"▶ 为什么这么干：{text}")

    def engine(self, mode: str, detail: str = "") -> None:
        line = f"▶ 谁来做：{mode}"
        if detail:
            line += f"（{detail}）"
        self.write(line)

    def result(self, text: str) -> None:
        self.write(f"▶ 本步结果：{text}")

    def bullet(self, text: str) -> None:
        self.write(f"  · {text}")

    def error(self, text: str) -> None:
        self.write(f"✗ {text}")

    def stage_done(self, summary: str) -> None:
        self.blank()
        self.write(f"✓ 阶段小结：{summary}")
        self.blank()

    def llm_round(
        self,
        purpose: str,
        *,
        request_brief: str = "",
        prompt_file: str = "",
        success: bool,
        response_brief: str = "",
        fallback: str = "",
    ) -> None:
        """记录一轮 Python → 大模型 → Python 的交互（人话版）。"""
        self._llm_round += 1
        self.blank()
        stage = self._current_stage or "流水线"
        self.write(f"{'─' * 40}")
        self.write(f"【大模型交互 · 第 {self._llm_round} 轮】{stage}")
        self.write(f"▶ 这轮要干什么：{purpose}")
        if request_brief:
            self.write(f"▶ Python 交给大模型的要求：{request_brief}")
        if prompt_file:
            self.write(f"▶ 提示词文件：{prompt_file}")
        if success:
            self.write(f"▶ 大模型返回：{response_brief or '成功（详见上文）'}")
        else:
            self.write(f"▶ 大模型返回：失败 — {response_brief or '无有效内容'}")
            if fallback:
                self.write(f"▶ Python 接下来：{fallback}")

    def log_llm_call(self, purpose: str, *, success: bool, detail: str = "") -> None:
        """兼容旧接口；新代码请优先用 llm_round。"""
        self.llm_round(
            purpose,
            success=success,
            response_brief=detail,
            fallback="自动退回规则引擎结果，主流程继续。" if not success else "",
        )

    def doc_fill(
        self,
        output_name: str,
        *,
        template_name: str,
        fill_mode: str,
        written: list[str] | None = None,
        skipped: list[str] | None = None,
        note: str = "",
    ) -> None:
        """记录 Python 写 Word/doc 的一轮结果。"""
        self._doc_fill_round += 1
        self.blank()
        self.write(f"{'─' * 40}")
        self.write(f"【Word 自动填写 · 第 {self._doc_fill_round} 份】{output_name}")
        self.write(f"▶ Python 做了什么：复制模版「{template_name}」→ 生成「{output_name}」")
        self.write(f"▶ 填写方式：{fill_mode}")
        written = written or []
        skipped = skipped or []
        if written:
            self.write("▶ 成功写进去的内容：")
            for item in written[:8]:
                self.bullet(item)
            if len(written) > 8:
                self.bullet(f"…… 还有 {len(written) - 8} 项")
        if skipped:
            self.write("▶ 没写进去（模版里找不到对应位置或源数据为空）：")
            for item in skipped[:6]:
                self.bullet(item)
        total = len(written) + len(skipped)
        if total:
            effect = f"共尝试 {total} 项，成功 {len(written)} 项"
            if skipped:
                effect += f"，跳过 {len(skipped)} 项"
            self.write(f"▶ 填写效果：{effect}")
        elif note:
            self.write(f"▶ 填写效果：{note}")
        else:
            self.write("▶ 填写效果：文件已复制生成，未检测到可写字段（请检查模版或提取结果）")

    def python_only(self, action: str, outcome: str) -> None:
        """纯 Python、不经过大模型的一步。"""
        self.blank()
        self.write(f"【纯 Python】{action}")
        self.write(f"▶ 结果：{outcome}")

    def _header(self) -> None:
        self.section("NMPA 注册文件审核 — 运行日志")
        self.write(f"开始时间：{self.started.strftime('%Y-%m-%d %H:%M:%S')}")
        self.write(f"触发来源：{self.source}")
        self.write(f"输入文件夹：{self.upload_dir}")
        self.write(f"输出文件夹：{self.output_dir}")
        self.write(f"是否启用大模型：{'是' if self.use_llm_requested else '否'}")
        self.blank()
        self.write("【日志怎么看？】")
        self.bullet("每个阶段开头有【当前阶段】，表示流水线跑到哪了。")
        self.bullet("【大模型交互】= Python 把什么要求交给了 DeepSeek，大模型回了什么。")
        self.bullet("【Word 自动填写】= Python 用 python-docx 往模版里写了哪些字段、哪些没写上。")
        self.bullet("缺文件、字段是否一致等「合规结论」仍由规则引擎判定，大模型只帮忙理解和写报告。")
        self.blank()
        self.write("【五阶段一览】")
        self.bullet("阶段1：扫描文件夹、统计页数")
        self.bullet("阶段2：对照附件4查缺文件（纯规则）")
        self.bullet("阶段3：从说明书提取字段（规则为主，可选用大模型精炼）")
        self.bullet("阶段4：自动填写 Word + 结构/一致性/格式核查")
        self.bullet("阶段5：生成四维度合规风险预警报告")

    def finish(self, result: Any) -> None:
        from core.llm_client import should_use_llm

        llm_active = should_use_llm(self.use_llm_requested)
        ended = datetime.now()
        elapsed = (ended - self.started).total_seconds()

        self.section("全部跑完 — 最终汇总")
        self.write(f"结束时间：{ended.strftime('%Y-%m-%d %H:%M:%S')}")
        self.write(f"总耗时：{elapsed:.1f} 秒")
        self.write(f"大模型交互轮数：{self._llm_round} 轮")
        self.write(f"Word 填写份数：{self._doc_fill_round} 份")
        self.blank()

        self.write("【技术分工（人话版）】")
        self.bullet("Python 固定流水线：全程参与（扫描、规则、填 Word、写报告）")
        self.bullet(
            f"大模型 DeepSeek：{'已调用' if llm_active else '未调用'}"
            + (f"（本次共 {self._llm_round} 轮）" if llm_active and self._llm_round else "")
        )
        self.bullet("自主 Agent 自主循环：无（按固定五阶段顺序执行）")
        self.blank()

        self.write("【最终结果】")
        n_files = len(result.file_list)
        n_comp = len(result.completeness_issues)
        n_cons = len(result.consistency_issues)
        n_struct = len(result.structure_issues)
        n_fmt = len(getattr(result, "format_issues", []))
        self.bullet(f"看了 {n_files} 个文件，自动填写了 {len(result.filled_files)} 份 Word/doc。")

        if n_comp == 0:
            self.bullet("完整性：没发现缺文件。")
        else:
            self.bullet(f"完整性：{n_comp} 个问题（例如缺 CH1.6、缺产品技术要求）。")
            for issue in result.completeness_issues[:4]:
                self.bullet(f"[{issue.severity}] {issue.message}")

        if result.extracted:
            ex = result.extracted
            if ex.confidence.get("_error"):
                self.bullet(f"信息提取：{ex.confidence['_error']}")
            else:
                llm_note = "大模型有参与精炼" if ex.llm_used else "纯规则正则"
                self.bullet(f"信息提取：从「{ex.source_file}」读到产品「{_clip(ex.product_name, 50)}」（{llm_note}）")

        if n_cons == 0:
            self.bullet("一致性：跨文档关键字段未发现冲突。")
        else:
            self.bullet(f"一致性：{n_cons} 处不一致，提交前务必人工核对。")
            for issue in result.consistency_issues[:3]:
                vals = "；".join(f"{k}={_clip(v, 25)}" for k, v in issue.values.items())
                self.bullet(f"{issue.label}：{vals}")

        if n_struct == 0 and n_fmt == 0:
            self.bullet("章节/格式：未发现明显缺失或不规范。")
        else:
            if n_struct:
                self.bullet(f"章节/必检项：{n_struct} 份文档有问题。")
            if n_fmt:
                self.bullet(f"格式规范：{n_fmt} 份文档有问题。")

        if result.filled_files:
            self.bullet("已生成的 Word 文件：")
            for fp in result.filled_files:
                self.bullet(Path(fp).name)

        if result.report_path:
            self.bullet(f"合规报告：{result.report_path}")

        self.blank()
        self.write(f"完整日志：{self.log_path}")
        self.write(f"最新副本：{self.latest_path}")

    def _flush(self) -> None:
        text = "\n".join(self._lines) + "\n"
        self.log_path.write_text(text, encoding="utf-8")
        self.latest_path.write_text(text, encoding="utf-8")
