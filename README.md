# 松岚听辨教室

教师校样并发行一册短音题，按学员签到顺序开轮和播放。学员逐席提交选项。教师登记揭晓，教室推进实际显示。关轮后，值班教师按席序核对正式答卷与分类复盘。

## 运行

使用 Python 3.11 标准库。在物化后的项目根目录运行 `python3 -B check_project.py`。直接进入同一完整套件可运行 `python3 -B -m unittest discover`。

运行 `python3 -B -m submission.http_service demo`，以两个本机 HTTP 监听端和独立临时库完成发行、播放、交卷、揭晓、关轮及重开复领。样例正确选项为 A，值 3 分。甲先选 A，得 3 分并计盲答。乙在实际揭晓后选 B，得 0 分并计已提示。丙未交。演示核对实测复盘并打印场景 JSON。

使用 `python3 -B -m submission.http_service serve --data ./day-data --score-port 8765 --room-port 8766` 保留当天资料。启动时会打印两个监听地址。默认素材目录为项目的 `samples`，可用 `--audio-dir` 指定本地素材目录。`grades.sqlite3` 保存发行、回合、答卷和复盘，`classroom.sqlite3` 保存揭晓任务及实显历史。重用数据目录会保留原结果。监听绑定于本机回环地址。

## JSON HTTP

以下入口均以 POST 发送 JSON 对象。回合号和发行版号是正整数。原请求号为非空字符串，在交卷、揭晓、关轮各自的操作类型内唯一。表中 `round_id` 为回合号，`request_id` 为原请求号。

| 监听端 | 路径 | 输入字段 | 结果 |
| --- | --- | --- | --- |
| 成绩 | `/proof` | `book`, `questions` | 校样结果，含题号、公共题面、音频参数和给分依据 |
| 成绩 | `/publish` | `book`, `questions` | 校验并追加发行，返回 `edition_id` |
| 成绩 | `/open_round` | `edition_id`, `question_id`, `seats` | 固定题面与按输入序排列的名单 |
| 成绩 | `/get_round` | `round_id` | 题面、名单、播放和开关状态 |
| 成绩 | `/read_prompt` | `round_id` | 本轮公共题面 |
| 成绩 | `/play_prompt` | `round_id` | 持久记录播放并交付完整 WAV 的 Base64 与公共题面 |
| 成绩 | `/submit` | `round_id`, `seat`, `request_id`, `choice` | `accepted` 首执或 `pending` |
| 成绩 | `/swap_seats` | `round_id`, `device_a`, `device_b`, `request_id` | `swapped` 两席新授权，或 `pending` |
| 成绩 | `/reveal` | `round_id`, `request_id` | 登记待显示，或复领 `shown` 原结局 |
| 成绩及教室 | `/apply_display` | `round_id`, `request_id` | 使已登记画面在教室生效，或复领原实显 |
| 教室 | `/current_display` | `round_id` | 当前生效画面及本轮实显次数 |
| 成绩 | `/lookup` | `round_id`, `kind`, `request_id` | `kind` 为 `submission`、`reveal` 或 `close`，按轮和原号读取 |
| 成绩 | `/close_round` | `round_id`, `request_id` | 结清后返回唯一 `closed` 复盘，未结清时为 `pending` |

`samples/daily.json` 是可直接提交给 `/proof` 或 `/publish` 的完整示例。每题的字段为 `id`、`prompt`、`audio`、`options`、`answer` 和 `points`。每个选项有 `id` 和 `label`。素材引用为文件名，例如 `two-pulses.wav.z64`，内容为 zlib 压缩后的 WAV 再做 Base64 编码。支持 8–48 kHz、1–2 声道、8 或 16 位 PCM，最长 3 秒。发行版保存解码后的 WAV 内容。因此后续替换源文件只影响再次发行。

教室显示的可观察生效点是 `/current_display` 可读取持久的答案画面。发令后可以暂缓 `/apply_display`。生效后即使回包丢失，同一原号仍可查实，重投不重复显示。答卷在实际揭晓前正式受理计 `blind`，揭晓后计 `hinted`。同号同参可续办或复领。答卷 `pending` 只有状态和身份，已定稿首执保留 `choice`、`correct`、整数 `points` 和首次 `category`。

无效输入返回 HTTP 400 和 `error`。未知原号、轮次或版号返回 404。原号异参、已经被占用的席位或关轮后的新操作返回 409。待查返回 202，成功返回 200。揭晓已登记时，关轮等待实显结清。一个关轮请求号保留本轮复盘的办理身份。已定稿复盘列出各席原选择、正确项与首执，未交卷席位使用 `missing` 并保留空选择和空分值。两类小计分别按正式行计算实交人数、总分和答对人数。零分题仍可有答对人数。

## 设备席位与调位

`/open_round` 的 `seats` 也接受 `{"device","student"}` 对象列表进入设备席位模式：`/open_round` 与 `/get_round` 额外返回按设备顺序排列的 `bindings`，每项含 `device`、`student` 和服务签发的 `authorization`，`seats` 以同一顺序列出学员。设备模式 `/submit` 改收 `device`、`authorization`，首执与复盘行额外记录实际交卷/关轮时的 `device`。`/swap_seats` 交换本轮两台不同设备、为两席换发新授权并作废旧授权；相同原号参数可续办或复领，调位未结清或仍有有效授权下的待办答卷时 `/close_round` 返回 202。完整约定与断点位见 [SEAT_SWAPS.md](SEAT_SWAPS.md)，业务核验见 `tests/test_seat_swap_behavior.py`，对照场景可运行 `python3 -B seat_swap_scene.py`。
