---
name: summary-table
description: Answers a request to summarize, review, compare, inventory or report on several things with a table first instead of long prose - a one-line conclusion, one table whose columns fit the question, then only the few items that need a decision. Use when the user asks to tổng kết, tổng hợp, kiểm kê, so sánh, liệt kê, list ra, báo cáo kết quả, "cho mình bảng", "where are we", "status of all of them", or asks for a table, or says a table is hard to read, has the wrong columns or does not match another one. Also use for results meant to be pasted into a tracker comment or a message. Not for explaining a concept or giving instructions.
---

# Summary table

The reader asks for a summary to decide or approve something, and often has to compare items. A paragraph per item hides the gaps; one table with the same columns for every item shows them. In this user's history the table requests come mostly at the end of a piece of work ("cho bảng tổng kết cuối cùng", "bảng số lượng suite trong mỗi module", "bảng kết quả chạy: số TC, pass, fail") and are often followed by a correction of the columns, so the columns are the part to get right.

## Steps

1. **Conclusion first, one line.** The answer to the question, with the count or the verdict ("6 of 7 repos clean, 1 has an unpushed commit").

2. **Pick the columns from what the reader will decide, not from what is easy to list.** Typical sets:

   | Request | Columns that usually work |
   |---|---|
   | Test or run results | Item, Total, Pass, Fail, Untestable or blocked, In progress, Note |
   | Status of several things | Item, State, What is open, Owner, Next step |
   | Inventory | Item, Where, Size or count, State |
   | Comparison or options | Option, Strength, Weakness, Cost or effort, Verdict |
   | Plan | Step, Action, Why first, Needs approval |

   Keep at most 6 columns on a terminal and 4 or 5 when the table will be pasted into a tracker comment, a chat message or an email: wide tables wrap badly there. Name the column after the question it answers ("What is open", not "Details").

3. **Match an earlier table.** If a similar table already exists in this conversation, in the same folder (the previous comment, the report of the sibling task) or the user pointed to one, copy its column names and order. Two reports of the same kind that look different cost the user a review round. If the user says to drop, merge or add a column, change that table and keep the change for the tables that follow.

4. **One table, short cells.** Cells hold a few words, a number or a status word used the same way throughout (Pass, Fail, Untestable, not "ok" in one row and "passed" in another). Put units in the header. Use names the reader sees (test case code, module, UI path), not internal ids. No emoji or check marks, no colours or HTML, no fenced code block (also not for commands: write them inline in backticks); plain Markdown pipes. When the text is for pasting elsewhere, put it between two `---` lines and add no quote marks.

5. **Long lists.** More than about 15 rows: group by category and show one row per group, or show the rows that need attention and say where the full list is (write it to `temp/` when it is large). Do not paste 40 rows into the chat.

6. **Under the table, only what needs the reader:** up to four lines, each with the owner and the action, labelled in the chat language (for example "Cần bạn quyết", "Việc còn mở"). Then one line saying what was not checked. Skip any of these when empty.

## Boundaries

- Do not pad: no recap of how the numbers were obtained unless asked, no history.
- Numbers come from the source, not from memory; if a figure could not be checked, say so in the cell or under the table.
- Reading and summarizing only. Posting the table anywhere is a separate step that needs the user's approval.
