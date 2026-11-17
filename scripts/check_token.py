#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GitHub token 权限诊断 —— 一次性定位「为什么创建 issue 被 403」。

用法:
    python3 scripts/check_token.py

注意：L3b「写第三方仓库探针」默认【禁用】。2026-11-17 bowenliang123 在
dsh-context#269 明确抗议 __cybermap_token_probe__ 这类往无关仓库开测试 issue
的行为（视为自动化骚扰铁证）。现仅当显式设置环境变量 ALLOW_THIRD_PARTY_PROBE=1
时才运行 L3b，日常诊断不碰任何第三方仓库。

判定逻辑（按 fine-grained PAT 的三层授权模型逐层探测）:
    L1 身份      : GET  /user                       -> token 本身有效
    L2 仓库读    : GET  /repos/{owner}/{repo}       -> 能否看到目标仓库
    L3 仓库写    : POST /repos/{owner}/{repo}/issues-> 能否创建 issue
    L4 scope     : 响应头 X-OAuth-Scopes            -> classic token 会显示 scope，fine-grained 不显示

失败时按现象给出对应修复动作，而不是只报 403。
"""
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN_FILE = os.path.join(ROOT, "outreach", ".token")
API = "https://api.github.com"

# 双对照探测：
#   自己的仓库  —— 验证 token 写权限本身是否开通（写自己的不会打扰别人）
#   第三方仓库  —— 验证能否给外部作者提 issue（这是本项目的核心需求）
PROBE_OWNER = "ohalo"
PROBE_REPO = "ohalo"
PROBE_THIRD_PARTY = "alchaincyf/nuwa-skill"


def get_token():
    env = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if env:
        return env.strip()
    if os.path.exists(TOKEN_FILE):
        with io.open(TOKEN_FILE, encoding="utf-8") as f:
            t = f.read().strip()
        if t:
            return t
    return None


def api(path, token=None, method="GET", payload=None):
    """返回 (http_code, json_body, headers)。不抛异常。"""
    url = path if path.startswith("http") else API + path
    data = None
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "cybermap-outreach",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", "replace")
            hdrs = {k: v for k, v in resp.headers.items()}
            try:
                parsed = json.loads(body) if body else {}
            except ValueError:
                parsed = {"_raw": body[:400]}
            return resp.status, parsed, hdrs
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        hdrs = {k: v for k, v in e.headers.items()} if e.headers else {}
        try:
            parsed = json.loads(body) if body else {}
        except ValueError:
            parsed = {"_raw": body[:400]}
        return e.code, parsed, hdrs
    except Exception as e:  # 网络层异常
        return 0, {"message": str(e)}, {}


def line(char="-", n=72):
    return char * n


def main():
    token = get_token()
    print("=" * 72)
    print("GitHub token 权限诊断")
    print("=" * 72)

    if not token:
        print("✗ 未找到 token。请设置 GITHUB_TOKEN 环境变量或写 outreach/.token")
        return 1

    print("token: %s%s (长度 %d)" % (token[:12], "..." + token[-4:], len(token)))
    is_fine = token.startswith("github_pat_")
    print("类型: %s" % ("fine-grained PAT (github_pat_)" if is_fine else "classic PAT (ghp_/github_pat_ 旧式)"))
    print()

    # ---- L1 身份 ----
    code, data, hdrs = api("/user", token=token)
    if code != 200:
        print("✗ L1 身份校验失败 (http=%s): %s" % (code, str(data.get("message"))[:120]))
        print("  → token 已失效 / 被吊销。请重新生成。")
        return 1
    login = data.get("login")
    print("✓ L1 身份: %s (类型 %s)" % (login, data.get("type")))

    scopes = hdrs.get("X-OAuth-Scopes")
    if scopes is not None:
        print("  scope 声明: %s" % scopes)
    else:
        print("  scope 声明: 无（fine-grained PAT 不返回此头，属正常）")
    print()

    # ---- L2 仓库读 ----
    code, data, hdrs = api("/repos/%s/%s" % (PROBE_OWNER, PROBE_REPO), token=token)
    if code != 200:
        print("✗ L2 读仓库失败 (http=%s): %s" % (code, str(data.get("message"))[:120]))
        print("  → token 连目标仓库都读不到，先解决仓库可见性。")
        return 1
    perms = data.get("permissions") or {}
    print("✓ L2 读仓库: %s/%s" % (PROBE_OWNER, PROBE_REPO))
    print("  账号权限字段: %s" % {k: v for k, v in perms.items() if v})
    if "issues" in perms:
        print("  issues 字段存在 -> %s" % perms.get("issues"))
    else:
        print("  issues 字段缺失 -> token 未被授予 Issues 权限（fine-grained 的典型信号）")
    print()

    # ---- L3a 写自己的仓库（验证 token 写权限是否开通）----
    print("→ L3a 写测试 A: 自己的仓库 %s/%s" % (PROBE_OWNER, PROBE_REPO))
    code_own, data_own, _ = api(
        "/repos/%s/%s/issues" % (PROBE_OWNER, PROBE_REPO), token=token, method="POST",
        payload={"title": "__cybermap_token_probe__", "body": "temporary permission probe"},
    )
    own_ok = code_own in (200, 201)
    if own_ok:
        num = data_own.get("number")
        print("  ✓ 创建成功 #%s" % num)
        c2, d2, _ = api("/repos/%s/%s/issues/%s" % (PROBE_OWNER, PROBE_REPO, num),
                       token=token, method="PATCH",
                       payload={"state": "closed", "state_reason": "not_planned"})
        print("  ✓ 已关闭清理 (http=%s)" % c2)
    else:
        print("  ✗ 失败 http=%s %s" % (code_own, str(data_own.get("message"))[:110]))
    print()

    # ---- L3b 写第三方仓库（默认禁用；2026-11-17 起因作者抗议改为显式 opt-in）----
    allow_3p = os.environ.get("ALLOW_THIRD_PARTY_PROBE") == "1"
    if not allow_3p:
        print("→ L3b 写测试 B: 【已跳过】默认不向第三方仓库 %s 开探针 issue。" % PROBE_THIRD_PARTY)
        print("   （作者已明确抗议此类行为；如需诊断请显式设置 ALLOW_THIRD_PARTY_PROBE=1）")
        code_3p, data_3p = 0, {}
        third_ok = None  # None = 未测试，不代表成功也不代表失败
        print()
    else:
        print("→ L3b 写测试 B: 第三方仓库 %s（显式 opt-in）" % PROBE_THIRD_PARTY)
        code_3p, data_3p, _ = api(
            "/repos/%s/issues" % PROBE_THIRD_PARTY, token=token, method="POST",
            payload={"title": "__cybermap_token_probe__", "body": "temporary permission probe"},
        )
        third_ok = code_3p in (200, 201)
        if third_ok:
            num3 = data_3p.get("number")
            print("  ✓ 创建成功 #%s" % num3)
            c3, d3, _ = api("/repos/%s/issues/%s" % (PROBE_THIRD_PARTY, num3),
                           token=token, method="PATCH",
                           payload={"state": "closed", "state_reason": "not_planned"})
            print("  ✓ 已关闭清理 (http=%s)" % c3)
        else:
            print("  ✗ 失败 http=%s %s" % (code_3p, str(data_3p.get("message"))[:110]))
        print()

    msg = str(data_3p.get("message") or "")
    if third_ok is None:
        # 未测第三方写，只凭「写自己仓库成功 + classic token」给出可用性判断
        if own_ok:
            print("=" * 72)
            print("结论: token 写自己的仓库正常；classic token 理论可写公开第三方仓库")
            print("      （本次未向第三方开探针，尊重作者意愿）。可以手动发送 issue。")
            print("=" * 72)
            print("注意: 发送前遵守 outreach/blocked.json 黑名单，勿联系明确拒绝的作者。")
            return 0
        print("=" * 72)
        print("结论: token 连自己的仓库都写不了，Issues 写权限未开通，无法发送。")
        print("=" * 72)
        return 1

    if own_ok and third_ok:
        print("=" * 72)
        print("结论: token 完全可用，可以开始批量发送 issue。")
        print("=" * 72)
        print()
        print("下一步: python3 scripts/run_outreach.py --limit 15 --dry-run   # 先看计划")
        print("        python3 scripts/run_outreach.py --limit 15              # 实际发送")
        return 0

    # --- 关键归因：写权限已通，但第三方写不了 ---
    if own_ok and not third_ok and code_3p == 403 and "personal access token" in msg.lower():
        print("=" * 72)
        print("结论: fine-grained PAT 无法用于本项目 —— 这是 GitHub 的设计限制，")
        print("      不是你配置错了。")
        print("=" * 72)
        print("""
证据链：
  A. 写自己的仓库  → 成功（说明 token 的 Issues 写权限【已正确开通】）
  B. 写第三方仓库  → 403（说明缺的不是权限，而是 token 类型）

GitHub 官方文档原文（Managing your personal access tokens）：
  "Only personal access tokens (classic) have write access for public
   repositories that are not owned by you or an organization that you
   are not a member of."

fine-grained PAT 的已知限制里明确写着：
  "Using fine-grained personal access token to contribute to public repos
   where the user is not a member."

原因：token 只能授予你账号【本身已拥有】的权限。你不是第三方仓库的
协作者，fine-grained token 就写不进去。

唯一解法：换成 classic token

  1. 打开 https://github.com/settings/tokens/new
     （注意是 /tokens/new，不是 /personal-access-tokens）
  2. Note 随便填，如 cybermap-outreach
  3. Expiration 建议 30 天（够用，用完可删）
  4. Select scopes 勾选唯一一项：
        ☑ public_repo      ← 只勾这一项就够
  5. Generate token
  6. 把新 token 给我（或自己写进 outreach/.token）

拿到 classic token 后：
  - 配额 5000/小时（和现在一样）
  - 能给任何第三方公开仓库提 issue ← 本项目刚需
  - 权限比 fine-grained 大，务必用完即删

不想换 token 的话，用不依赖 token 的手动队列：
  python3 scripts/build_manual_queue.py
  → outreach/manual-queue.html（标题正文已预填，点 Submit 即可）
""")
        return 2

    if not own_ok:
        msg = str(data_own.get("message") or "")

    # ---- L4 归因 ----
    print("=" * 72)
    print("归因分析")
    print("=" * 72)

    if code == 403 and "personal access token" in msg.lower():
        if is_fine:
            print("""
fine-grained PAT 的写权限由【两个独立开关】共同决定，**两个都必须对**：

  □ 开关一：Repository permissions -> Issues = Read and write
  □ 开关二：Repository access = All repositories
            （或 Only select repositories 且确实勾选了该仓库）

最常见的错误：只改了开关一，开关二仍是
「Public repositories (read-only)」—— 这个选项下即使 Issues 给了
Read and write，写操作依然被拒，表现就是读正常、写 403。

修复路径（推荐，约 1 分钟）:
  1. 打开 https://github.com/settings/personal-access-tokens
  2. 找到本 token（后缀 %s）-> Edit
  3. Repository permissions -> Issues -> Read and write
  4. Repository access -> All repositories
  5. 页面底部 Save（务必点，否则不生效）
  6. 回来重跑: python3 scripts/check_token.py

备选（更稳，classic token 的 scope 一目了然）:
  https://github.com/settings/tokens/new -> 只勾 public_repo -> 生成新 token
""" % token[-4:])
        else:
            print("""
classic token 缺少 scope。重新生成并勾选：
  https://github.com/settings/tokens/new -> 勾选 public_repo -> Generate
""")
        return 2

    if code == 403:
        print("""
403 但报错文案不是权限问题。常见原因:
  - 仓库开启了 issue 限制 / 只有特定组织成员可提 issue
  - 该 token 被组织策略限制
  - 账号本身被限制（速率/滥用封禁）
请先在浏览器里手动给 %s/%s 提一条 issue，确认账号本身没被封。
""" % (PROBE_OWNER, PROBE_REPO))
        return 3

    if code == 401:
        print("401: token 无效或已吊销，请重新生成。")
        return 4

    if code == 422:
        print("422: 请求体被拒（Validation failed）。这说明【写权限其实是有的】")
        print("     只是 payload 不被接受 —— 是好消息。详细: %s" % msg[:200])
        return 0

    print("其他状态码 http=%s: %s" % (code, msg[:200]))
    print("网络或服务端异常，稍后重试。")
    return 5


if __name__ == "__main__":
    sys.exit(main())
