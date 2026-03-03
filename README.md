# Canvas MCP Server

A local [MCP](https://modelcontextprotocol.io/) server that lets you manage Canvas LMS — courses, assignments, grades, modules, and more — from any MCP-compatible client like **Claude Desktop**, **Kiro**, or **Amazon Q Developer**.

---

## Quick Start

### 1. Get a Canvas API Token

1. Log in to your Canvas instance
2. Go to **Account → Settings**
3. Scroll to **Approved Integrations** and click **+ New Access Token**
4. Give it a name, click **Generate Token**, and copy it

### 2. Install

```bash
git clone <repo-url> && cd canvas-mcp-local
pip install .
```

### 3. Run

```bash
export CANVAS_API_TOKEN="your-token-here"
export CANVAS_BASE_URL="https://myschool.instructure.com"
canvas-mcp
```

That's it — the server is now listening on stdio for MCP messages.

---

## Connect to Your MCP Client

### Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "canvas": {
      "command": "canvas-mcp",
      "env": {
        "CANVAS_API_TOKEN": "your-token-here",
        "CANVAS_BASE_URL": "https://myschool.instructure.com"
      }
    }
  }
}
```

### Kiro

Add to your Kiro MCP configuration:

```json
{
  "mcpServers": {
    "canvas": {
      "command": "canvas-mcp",
      "env": {
        "CANVAS_API_TOKEN": "your-token-here",
        "CANVAS_BASE_URL": "https://myschool.instructure.com"
      }
    }
  }
}
```

> **Tip:** If you installed into a virtualenv, use the full path to the `canvas-mcp` binary, e.g. `"/path/to/venv/bin/canvas-mcp"`.

---

## Available Tools

### Student

| Tool | Description |
|------|-------------|
| `list_upcoming_assignments` | Upcoming assignments across all courses (1–60 days ahead) |
| `check_submission_status` | Check if you've submitted a specific assignment |
| `view_my_grades` | Your grades for all assignments in a course |
| `view_todo_list` | Your Canvas TODO list |
| `schedule_canvas_event` | Create a calendar event (study blocks, review sessions) |

### Instructor

| Tool | Description |
|------|-------------|
| `get_my_courses` | List your active courses |
| `find_course_files` | Search or list files in a course |
| `create_course_module` | Create a new module |
| `add_item_to_module` | Add an item to an existing module |
| `create_course_assignment` | Create an assignment (draft by default) |
| `post_course_announcement` | Post an announcement to a course |
| `create_course_page` | Create a wiki/content page (draft by default) |
| `get_assignment_grade_summary` | Grade stats: submitted, graded, missing, avg/high/low |

---

## Example Workflows

### Student: "What's due this week?"

> "Show me everything that's due in the next 7 days."

The agent calls: `list_upcoming_assignments(days_ahead=7)` → returns assignments sorted by due date across all courses

### Student: "Did I turn in my homework?"

> "Did I submit the Lab 3 assignment for CS 101?"

The agent calls: `get_my_courses` → `check_submission_status(course_id, assignment_id)` → returns submitted_at, late, missing, score

### Student: "How am I doing in this class?"

> "What are my grades in Math 200?"

The agent calls: `get_my_courses` → `view_my_grades(course_id)` → returns all assignment scores, late/missing flags

### Student: "What do I need to work on?"

> "What's on my Canvas TODO list?"

The agent calls: `view_todo_list()` → returns unsubmitted assignments and other items needing attention

### Student: "Schedule study time for my midterm"

> "Block off 2 hours on Saturday afternoon to study for my CS 101 midterm."

The agent calls: `schedule_canvas_event(title="CS 101 Midterm Study", start_at="...", end_at="...")`

### Instructor: Build a course module in one prompt

> "Create a 'Week 7 — Neural Networks' module in my CS 301 course with a reading page on backpropagation and a homework assignment worth 50 points due next Friday."

The agent chains: `get_my_courses` → `create_course_module` → `create_course_page` → `create_course_assignment` → `add_item_to_module` × 2

### Instructor: Check assignment grades

> "How did students do on the Week 3 Problem Set in Math 200?"

The agent calls: `get_my_courses` → `get_assignment_grade_summary` → returns avg, high, low, submission count, missing count

### Instructor: Find course files

> "Find the syllabus in my English 102 course."

The agent calls: `get_my_courses` → `find_course_files(search_term="syllabus")`

### Instructor: Post an announcement

> "Remind my Biology 101 students that the midterm is next Wednesday and to review chapters 5–8."

The agent calls: `get_my_courses` → `post_course_announcement`

---

## Requirements

- Python 3.10+
- A Canvas LMS instance with API access
- A valid Canvas API token

## License

MIT-0
