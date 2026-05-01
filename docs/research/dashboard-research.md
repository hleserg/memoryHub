# Dashboard Research for Atman Project

## Executive Summary

This research evaluates 10 self-hosted dashboard solutions for the Atman project, focusing on the ability to provide a unified view of system health, development quality, and live data across multiple projects. The key requirements are:

- Self-hosted deployment
- Easy integration of new data sources
- Command execution from UI (e.g., running tests)
- Live data display (not just static metrics)
- Compact, multi-project support on one screen
- Workspace saving and configuration management

**Recommendation:** For Atman's needs, **Streamlit** is the recommended solution for MVP, with **Grafana** as a complementary tool for infrastructure monitoring.

---

## 1. Systems Analyzed

### 1.1 Grafana

**Type:** Infrastructure & Operations Monitoring  
**License:** AGPLv3  
**Language:** Go + TypeScript  
**GitHub Stars:** ~60k+

**Strengths:**
- Industry standard for real-time time-series data visualization
- Excellent alerting system
- Extensive data source plugins (Prometheus, InfluxDB, PostgreSQL, etc.)
- Built-in authentication and RBAC
- Multi-tenant workspace support
- Easy self-hosting via Docker

**Weaknesses:**
- Primarily designed for metrics/monitoring, not general BI
- Not suitable for displaying structured data (e.g., database tables)
- Limited support for triggering commands from UI (requires external webhooks)
- Not ideal for "live data exploration" beyond time-series metrics

**Fit for Atman:**
- ✅ Excellent for system health monitoring (container status, error rates)
- ✅ Self-hosted and mature
- ❌ Not suitable for displaying FactRecords, ExperienceRecords, or running tests
- ⚠️ Would require complementary tool for non-metrics use cases

**Rating:** 7/10 (excellent at what it does, but narrow scope)

---

### 1.2 Metabase

**Type:** Self-Service Business Intelligence  
**License:** AGPLv3 (Core), Commercial (Enterprise)  
**Language:** Clojure + TypeScript  
**GitHub Stars:** ~38k+

**Strengths:**
- Visual query builder + SQL mode
- Easy to add SQL-based data sources
- Good for non-technical users
- Multi-user workspace management
- Dashboard sharing and embedding
- Self-hosted deployment is straightforward

**Weaknesses:**
- No built-in command execution (tests must be triggered externally)
- Limited real-time capabilities (periodic refresh only)
- More suited for analytics than operational dashboards
- No native support for non-SQL data sources without ETL

**Fit for Atman:**
- ✅ Good for exploring FactRecords, ExperienceRecords
- ✅ Easy to set up and use
- ❌ Cannot run tests from UI
- ❌ No real-time streaming data

**Rating:** 6/10 (good for data exploration, missing action capabilities)

---

### 1.3 Apache Superset

**Type:** Scalable Analytics & Visualization  
**License:** Apache 2.0  
**Language:** Python + TypeScript  
**GitHub Stars:** ~61k+

**Strengths:**
- Modern, feature-rich BI platform
- SQL Lab for ad-hoc queries
- Extensive visualization library
- Supports MongoDB (as of 2026), PostgreSQL, MySQL, etc.
- Advanced RBAC and multi-tenant support
- Self-hosted via Docker, Kubernetes (Helm chart available)

**Weaknesses:**
- Complex to set up and configure
- No built-in command execution
- Requires database-centric workflows
- Higher learning curve than Metabase

**Fit for Atman:**
- ✅ Excellent for complex data analysis
- ✅ SQL Lab useful for exploring records
- ❌ Overkill for simple use cases
- ❌ No test execution from UI

**Rating:** 6.5/10 (powerful but heavy)

---

### 1.4 Streamlit

**Type:** Rapid Python Data Apps  
**License:** Apache 2.0  
**Language:** Python  
**GitHub Stars:** ~31k+

**Strengths:**
- Extremely fast to prototype
- Write entire app in pure Python
- Can execute arbitrary Python code (tests, scripts, data pipelines)
- Real-time updates via `st.rerun()` and session state
- Easy to deploy (Docker, Streamlit Cloud, or self-hosted)
- Native support for live data via background threads or async

**Weaknesses:**
- Linear execution model (re-runs entire script on interaction)
- Performance bottlenecks with large datasets (requires caching)
- Limited built-in RBAC (community features, not enterprise-grade)
- Not suitable for complex, multi-user production apps

**Fit for Atman:**
- ✅ **Perfect for MVP**: can display system health, run tests, show live data
- ✅ Simple to add new data sources (just Python code)
- ✅ Can trigger shell commands, run pytest, display results
- ✅ Compact: one script = one dashboard
- ⚠️ Requires custom code for multi-project workspace saving

**Rating:** 9/10 (best fit for Atman MVP)

---

### 1.5 Retool

**Type:** Internal Tools Platform  
**License:** Proprietary  
**Language:** JavaScript + Python support  
**Pricing:** Self-hosted available on **Enterprise plan only** (as of 2026)

**Strengths:**
- Drag-and-drop UI builder
- Excellent for internal tools and admin panels
- Can execute JavaScript/Python code (`code-executor` sandboxed)
- Supports automated testing via Webdriver (Cypress, Playwright)
- Multi-project "Spaces" for organization
- Source control integration (Git)
- Wide range of data source integrations

**Weaknesses:**
- **Self-hosted now Enterprise-only** (expensive, no free self-hosted option)
- Proprietary, not open source
- Overkill for simple dashboards

**Fit for Atman:**
- ✅ Excellent command execution and test running capabilities
- ✅ Multi-project workspace support
- ❌ **Not suitable due to Enterprise pricing** (self-hosted no longer free)
- ❌ Proprietary, not aligned with open-source ethos

**Rating:** 7/10 (great features, but cost-prohibitive)

---

### 1.6 Appsmith

**Type:** Low-Code Internal Tools  
**License:** Apache 2.0  
**Language:** Java + TypeScript  
**GitHub Stars:** ~32k+

**Strengths:**
- Open-source, free self-hosted via Docker
- Drag-and-drop UI with 50+ widgets
- Supports 30+ data sources (SQL, NoSQL, REST APIs, GraphQL)
- Custom logic via JavaScript
- Built-in RBAC
- Git-based version control

**Weaknesses:**
- Focused on CRUD operations and forms, not dashboards
- Less suitable for real-time data streaming
- JavaScript-centric (not Python-native)
- UI builder adds friction for rapid prototyping

**Fit for Atman:**
- ✅ Good for multi-project internal tools
- ⚠️ More complex than needed for MVP
- ❌ Not optimized for live data dashboards
- ❌ Less flexible than pure code approach (Streamlit)

**Rating:** 6/10 (useful but not ideal)

---

### 1.7 Budibase

**Type:** Low-Code App Platform  
**License:** GPL v3  
**Language:** JavaScript + TypeScript  
**GitHub Stars:** ~21k+

**Strengths:**
- Free self-hosted deployment (Docker)
- Automatic CRUD interface generation from data sources
- Built-in automation workflows (triggers + actions)
- Supports 15+ data sources (SQL, REST APIs)
- AI app generation features (as of 2026)
- Custom RBAC, SSO, audit logs

**Weaknesses:**
- Similar to Appsmith: CRUD-focused, not dashboard-focused
- Limited real-time capabilities
- JavaScript expressions for logic (not Python)
- UI builder adds overhead

**Fit for Atman:**
- ✅ Fast app generation
- ⚠️ Better for internal tools than dashboards
- ❌ Not optimized for live data
- ❌ Less flexible than code-first approach

**Rating:** 6/10 (similar to Appsmith)

---

### 1.8 Evidence

**Type:** Code-First BI (SQL + Markdown)  
**License:** MIT  
**Language:** JavaScript (Svelte)  
**GitHub Stars:** ~3k+

**Strengths:**
- Git-based BI: reports defined in SQL + Markdown
- Version-controlled dashboards
- Static site generation (fast, secure)
- Great for embedding in documentation
- Self-hosted via Node.js or static hosting

**Weaknesses:**
- Static generation model (not real-time)
- Limited interactivity (read-only dashboards)
- No command execution (by design)
- Requires SQL + Markdown workflow

**Fit for Atman:**
- ✅ Excellent for documentation-style reporting
- ❌ Cannot run tests or execute commands
- ❌ Not suitable for live operational dashboards
- ❌ Static output, not dynamic

**Rating:** 5/10 (wrong paradigm for Atman)

---

### 1.9 Panel (HoloViz)

**Type:** Python Dashboarding Library  
**License:** BSD-3-Clause  
**Language:** Python  
**GitHub Stars:** ~4k+

**Strengths:**
- Full Jupyter notebook support
- Native PyData ecosystem integration (HoloViews, hvPlot, Datashader)
- Reactive APIs for complex interactivity
- Real-time streaming data support
- Can trigger Python functions from UI
- Self-hosted via standard Python deployment

**Weaknesses:**
- Steeper learning curve than Streamlit
- Requires more boilerplate code
- Less popular (smaller community)
- Not as polished for rapid prototyping

**Fit for Atman:**
- ✅ Supports live data and command execution
- ✅ Python-native
- ⚠️ More complex than Streamlit for simple use cases
- ⚠️ Requires more setup

**Rating:** 7.5/10 (powerful but higher friction)

---

### 1.10 Plotly Dash

**Type:** Analytical Web Apps (Python)  
**License:** MIT  
**Language:** Python  
**GitHub Stars:** ~21k+

**Strengths:**
- Production-grade Python dashboards
- Built on Flask + React.js
- Complex interactivity via callbacks
- Live data updates via `dcc.Interval` components
- Can trigger Python functions from UI
- Extensive ecosystem (Dash Enterprise, Dash Bootstrap Components)
- Self-hosted deployment

**Weaknesses:**
- More verbose than Streamlit
- Callback-based architecture requires more boilerplate
- Authentication/RBAC requires custom setup (or paid Dash Enterprise)

**Fit for Atman:**
- ✅ Production-ready
- ✅ Supports live data and command execution
- ⚠️ More complex than Streamlit for MVP
- ⚠️ Requires more code for same functionality

**Rating:** 8/10 (excellent but heavier than needed)

---

## 2. Comparison Table

| Solution | Self-Hosted | Easy Data Source | Command Execution | Live Data | Multi-Project | Workspace Saving | Complexity | **Score** |
|----------|-------------|------------------|-------------------|-----------|---------------|------------------|------------|-----------|
| **Grafana** | ✅ Docker | ✅ Many plugins | ❌ (webhooks only) | ✅ Time-series | ✅ | ✅ Folders | Low | 7/10 |
| **Metabase** | ✅ Docker | ✅ SQL databases | ❌ | ⚠️ Polling | ✅ | ✅ Dashboards | Low | 6/10 |
| **Superset** | ✅ Docker/K8s | ✅ SQL + MongoDB | ❌ | ⚠️ Polling | ✅ | ✅ Advanced | High | 6.5/10 |
| **Streamlit** | ✅ Docker | ✅ Pure Python | ✅ Full Python | ✅ Real-time | ⚠️ Manual | ⚠️ Custom | Low | **9/10** |
| **Retool** | ❌ Enterprise | ✅ Many | ✅ JS/Python | ✅ | ✅ Spaces | ✅ Git | Medium | 7/10 |
| **Appsmith** | ✅ Docker | ✅ 30+ sources | ⚠️ JS only | ⚠️ Limited | ✅ | ✅ Git | Medium | 6/10 |
| **Budibase** | ✅ Docker | ✅ 15+ sources | ⚠️ JS only | ⚠️ Limited | ✅ | ✅ | Medium | 6/10 |
| **Evidence** | ✅ Node.js | ✅ SQL | ❌ | ❌ Static | ⚠️ Manual | ✅ Git | Low | 5/10 |
| **Panel** | ✅ Python | ✅ Python code | ✅ Python | ✅ Real-time | ⚠️ Manual | ⚠️ Custom | Medium | 7.5/10 |
| **Dash** | ✅ Python | ✅ Python code | ✅ Python | ✅ Real-time | ⚠️ Manual | ⚠️ Custom | Medium | 8/10 |

**Legend:**
- ✅ Full support / Easy
- ⚠️ Partial support / Requires custom work
- ❌ Not supported / Difficult

---

## 3. Recommended Solution

### Primary Recommendation: **Streamlit** (for MVP)

**Why Streamlit?**

1. **Fastest Time to Value:**
   - Pure Python: no JavaScript, no YAML config, no drag-and-drop
   - Single file can implement entire dashboard
   - Minimal learning curve for Python developers

2. **Meets All Core Requirements:**
   - ✅ Self-hosted (Docker, one-line deployment)
   - ✅ Easy data sources (just import Python libraries)
   - ✅ Command execution (run shell commands, pytest, scripts)
   - ✅ Live data (session state, background threads, `st.rerun()`)
   - ⚠️ Multi-project support (requires custom tabs or pages)
   - ⚠️ Workspace saving (requires custom config storage)

3. **Perfect for Atman Use Cases:**
   - Display container health (query Docker API)
   - Show test results (run pytest, parse output)
   - Display live data from PostgreSQL/MongoDB (use SQLAlchemy, pymongo)
   - Trigger operations (buttons → Python functions)

4. **Low Maintenance:**
   - No complex setup or configuration
   - No database required (unless storing dashboards)
   - Easy to extend and customize

**Limitations to Accept:**
- Not enterprise-grade RBAC (for multi-user environments)
- Requires custom code for workspace persistence
- Performance tuning needed for large datasets

**Mitigation:**
- Use `@st.cache_data` for expensive operations
- Store workspace configs in JSON/YAML files or lightweight DB
- Add basic auth via `streamlit-authenticator` library

---

### Complementary Tool: **Grafana** (for Infrastructure Monitoring)

**Why add Grafana?**

Grafana excels at **time-series monitoring**, which Streamlit is not optimized for. Use Grafana for:
- Container health metrics (via Prometheus + cAdvisor)
- Error rate dashboards (via Loki or PostgreSQL logs)
- Alerting (e.g., notify when tests fail)

**Integration:**
- Embed Grafana panels in Streamlit using `st.components.v1.iframe()`
- Or: keep separate Grafana instance for ops team, Streamlit for dev team

---

### Alternative: **Dash** (if you need production-grade Python dashboards)

If Streamlit's simplicity becomes a limitation (e.g., complex state management, multi-user sessions), migrate to **Dash**:
- More verbose but more structured
- Better for production apps with complex interactions
- Easier to test (Dash has built-in testing framework)

---

## 4. MVP Dashboard for Atman

### 4.1 What to Show First (Priority Order)

#### **Page 1: System Health** (Essential)
Display this information on the main dashboard:

1. **Container Status**
   - List of containers: `atman-backend`, `atman-db`, `atman-scheduler`, etc.
   - Status: ✅ Running / ⚠️ Degraded / ❌ Down
   - Uptime, CPU, memory usage (via Docker API)

2. **Last Successful Deploy**
   - Timestamp of last deploy
   - Git commit hash + message
   - Deployment log link (if available)

3. **Recent Errors (24h window)**
   - Count of errors by severity (ERROR, CRITICAL)
   - List of recent error messages (top 10)
   - Link to full logs

**Data Sources:**
- Docker API (via `docker` Python library)
- PostgreSQL logs table or Loki
- Git metadata (via `gitpython` library)

**UI Components:**
- Status cards with icons (✅/❌)
- Simple table or list for errors
- Line chart for error rate over time (optional)

---

#### **Page 2: Tests** (High Priority)

1. **Run Tests Button**
   - Dropdown: Select test suite (unit, integration, e2e)
   - Button: "Run Tests" → triggers `pytest` command
   - Live output: stream test results in real-time
   - Summary: X passed, Y failed, Z skipped

2. **Recent Test Runs**
   - Table: timestamp, suite, status, duration
   - Link to full test report (HTML or JSON)

3. **Test Coverage**
   - Overall coverage percentage
   - Coverage by module (optional)

**Implementation:**
```python
import streamlit as st
import subprocess

if st.button("Run Unit Tests"):
    with st.spinner("Running tests..."):
        result = subprocess.run(
            ["pytest", "tests/unit", "-v"],
            capture_output=True,
            text=True
        )
        st.text(result.stdout)
        if result.returncode == 0:
            st.success("✅ All tests passed!")
        else:
            st.error("❌ Some tests failed")
```

**Data Sources:**
- Shell command execution (`subprocess`)
- Test results parser (pytest JSON output)
- Coverage data (via `coverage.py`)

---

#### **Page 3: Live Data** (Medium Priority)

1. **Data Store Overview**
   - Total records: FactRecords, ExperienceRecords, etc.
   - Recent records (last 10)
   - Record creation rate (records/hour)

2. **Interactive Query**
   - Simple query builder: filter by type, timestamp, tags
   - Display results in table
   - Export to CSV (optional)

3. **Data Changes Timeline**
   - Chart showing record creation over time
   - Highlight anomalies (spikes, gaps)

**Data Sources:**
- PostgreSQL or MongoDB (via SQLAlchemy or pymongo)
- Use `st.dataframe()` or `st.table()` for display

---

#### **Page 4: PR Status** (Low Priority)

1. **Open PRs**
   - List of open PRs with title, author, status
   - CI/CD status (✅ passed / ❌ failed / ⏳ running)
   - Link to GitHub

2. **Recent Merges**
   - Last 5 merged PRs with timestamps

**Data Sources:**
- GitHub API (via `PyGithub` library)

---

### 4.2 MVP Architecture

```
┌─────────────────────────────────────────┐
│        Streamlit Dashboard              │
│  (Single Python App, Multi-Page Layout) │
└─────────────────────────────────────────┘
                    │
        ┌───────────┼───────────┐
        │           │           │
   ┌────▼────┐ ┌───▼───┐ ┌────▼─────┐
   │ Docker  │ │ PostgreSQL │ │ GitHub  │
   │  API    │ │  /MongoDB  │ │   API   │
   └─────────┘ └───────────┘ └──────────┘
```

**Tech Stack:**
- **Frontend:** Streamlit
- **Backend:** Python 3.12+
- **Data:** PostgreSQL/MongoDB (via SQLAlchemy/pymongo)
- **Infra:** Docker, Docker Compose
- **Deployment:** Self-hosted (Docker container)

**File Structure:**
```
atman-dashboard/
├── dashboard.py          # Main Streamlit app
├── pages/
│   ├── 1_system_health.py
│   ├── 2_tests.py
│   ├── 3_live_data.py
│   └── 4_pr_status.py
├── utils/
│   ├── docker_client.py
│   ├── db_client.py
│   └── github_client.py
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

---

### 4.3 MVP Development Plan

**Phase 1: System Health (Week 1)**
- Set up Streamlit skeleton
- Connect to Docker API
- Display container status
- Show recent errors from logs

**Phase 2: Tests (Week 2)**
- Add "Run Tests" button
- Parse and display pytest output
- Store test history (SQLite or JSON file)

**Phase 3: Live Data (Week 3)**
- Connect to PostgreSQL/MongoDB
- Display FactRecords, ExperienceRecords
- Add simple filtering

**Phase 4: PR Status (Week 4)**
- Integrate GitHub API
- Display open PRs and CI status

**Phase 5: Polish & Deploy (Week 5)**
- Add authentication (optional)
- Dockerize and deploy
- Write documentation

---

## 5. Implementation Checklist

- [ ] Set up Streamlit project structure
- [ ] Connect to Docker API for container status
- [ ] Implement "Run Tests" button with live output
- [ ] Connect to PostgreSQL/MongoDB for data display
- [ ] Add GitHub integration for PR status
- [ ] Dockerize dashboard application
- [ ] Write deployment documentation
- [ ] (Optional) Add Grafana for time-series metrics
- [ ] (Optional) Implement workspace/config persistence

---

## 6. Future Enhancements (Post-MVP)

1. **Multi-Project Support:**
   - Config file with list of projects
   - Dropdown to switch between projects
   - Per-project data source configs

2. **Workspace Saving:**
   - Save dashboard layouts to JSON
   - Load/save custom queries
   - User preferences (themes, defaults)

3. **Alerting:**
   - Email/Slack notifications when tests fail
   - Alerts for container downtime
   - Anomaly detection in data rates

4. **Advanced Analytics:**
   - Trend analysis (test failure rates over time)
   - Data quality metrics (missing fields, schema violations)
   - Performance profiling (slow queries, API latency)

5. **Migration to Dash (if needed):**
   - If Streamlit limitations become blocking
   - Refactor to Dash's callback architecture
   - Add proper testing with `dash.testing`

---

## 7. Conclusion

For the Atman project's MVP dashboard, **Streamlit** is the clear winner:
- Fastest to implement
- Python-native (matches project stack)
- Supports all core requirements (tests, live data, command execution)
- Self-hosted and open source

**Grafana** should be added as a complementary tool for infrastructure monitoring (containers, logs, alerts).

The MVP dashboard should focus on **System Health** and **Tests** first, as these provide immediate visibility into what agents are doing and whether the system is working. Live data exploration and PR status can be added incrementally.

**Estimated MVP Timeline:** 3-4 weeks for a functional, self-hosted dashboard with core features.

---

**Document Version:** 1.0  
**Last Updated:** 2026-04-30  
**Author:** Cloud Agent (Cursor)
