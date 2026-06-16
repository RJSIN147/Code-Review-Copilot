# 🤖 Code Reviewer Agent

An **autonomous AI-powered code review agent** that analyzes GitHub Pull Requests using advanced language models and provides comprehensive code quality insights through intelligent multi-agent workflows.

[![Python](https://img.shields.io/badge/python-3.13-blue)](.)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.116-green)](.)
![GitHub Actions Workflow Status](https://img.shields.io/github/actions/workflow/status/zingzy/code-review-agent/ci.yaml)
![Codecov](https://img.shields.io/codecov/c/github/zingzy/code-review-agent)
[![Code Style](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

## 🚀 Features

- **🧠 AI-Powered Analysis**: Multi-agent LangGraph workflow with intelligent decision-making
- **🔄 Async Processing**: Celery-based distributed task queue for scalable analysis
- **📊 Comprehensive Reports**: Security, performance, style, and maintainability insights
- **🐙 GitHub Integration**: Seamless GitHub API integration with rate limiting and caching
- **🗄️ Type-Safe Storage**: PostgreSQL with SQLModel ORM for robust data persistence
- **⚡ Redis Infrastructure**: High-performance caching and message brokering

## 🏗️ System Architecture

```mermaid
graph TB
    subgraph "Client Layer"
        Client[REST Client]
        Browser[Web Browser]
    end

    subgraph "API Gateway"
        FastAPI[FastAPI Server<br/>• Authentication<br/>• Validation<br/>• Documentation]
    end

    subgraph "Processing Layer"
        Celery[Celery Workers<br/>• Task Queue<br/>• Background Processing<br/>• Progress Tracking]

        subgraph "AI Agents"
            LangGraph[LangGraph Workflow<br/>• Decision Making<br/>• File Prioritization]
            LLM[LLM Service<br/>• Code Analysis<br/>• Issue Detection]
        end
    end

    subgraph "External Services"
        GitHub[GitHub API<br/>• PR Data<br/>• File Content<br/>• Metadata]
        OpenAI[OpenAI/Pollinations<br/>• GPT Models<br/>• Code Analysis]
    end

    subgraph "Data Layer"
        PostgreSQL[(PostgreSQL<br/>• Task Storage<br/>• Analysis Results<br/>• Audit Logs)]
        Redis[(Redis<br/>• Message Queue<br/>• Caching<br/>• Session Store)]
    end

    Client --> FastAPI
    Browser --> FastAPI
    FastAPI --> Celery
    Celery --> LangGraph
    LangGraph --> LLM
    LLM --> OpenAI
    Celery --> GitHub
    FastAPI --> PostgreSQL
    Celery --> PostgreSQL
    FastAPI --> Redis
    Celery --> Redis
    LangGraph --> Redis

    classDef api fill:#e1f5fe
    classDef processing fill:#f3e5f5
    classDef storage fill:#e8f5e8
    classDef external fill:#fff3e0

    class FastAPI api
    class Celery,LangGraph,LLM processing
    class PostgreSQL,Redis storage
    class GitHub,OpenAI external
```

## 🤖 AI Agent Workflow

```mermaid
graph TD
    Start([PR Analysis Request]) --> Triage[AI Triage Node<br/>• Examine PR metadata<br/>• Identify critical files<br/>• Set analysis strategy]

    Triage --> FileLoop{Files to Analyze?}

    FileLoop -->|Yes| AnalyzeFile[File Analysis Node<br/>• Deep code analysis<br/>• Issue detection<br/>• LLM integration]

    AnalyzeFile --> UpdateProgress[Update Progress<br/>• Status tracking<br/>• Real-time updates]

    UpdateProgress --> FileLoop

    FileLoop -->|No| Synthesize[Synthesis Node<br/>• Aggregate findings<br/>• Generate summary<br/>• Calculate metrics]

    Synthesize --> SaveResults[Save Results<br/>• Database storage<br/>• Cache updates]

    SaveResults --> Complete([Analysis Complete])

    subgraph "AI Decision Points"
        Triage
        AnalyzeFile
        Synthesize
    end

    subgraph "Data Operations"
        UpdateProgress
        SaveResults
    end

    classDef ai fill:#e3f2fd
    classDef data fill:#e8f5e8
    classDef flow fill:#fff3e0

    class Triage,AnalyzeFile,Synthesize ai
    class UpdateProgress,SaveResults data
    class Start,Complete,FileLoop flow
```

## 🛠️ Technology Stack

### **Backend Framework**

- **FastAPI** - Modern async web framework
- **SQLModel** - Type-safe database ORM combining Pydantic and SQLAlchemy
- **Celery** - Distributed task queue with Redis broker for async processing
- **Redis** - High-performance caching and message broker
- **PostgreSQL** - Robust relational database with JSON support
- **UV** - Lightning-fast Python package manager and dependency resolver

### **AI & Analysis Engine**

- **LangGraph** - Advanced AI workflow orchestration with state management
- **OpenAI/Pollinations** - Multiple LLM provider support for code analysis
- **PyGithub** - Comprehensive GitHub API integration with rate limiting
- **Instructor** - Structured LLM output validation with Pydantic models
- **Custom Analysis Tools** - Specialized code analysis utilities and detectors

### **Development & Infrastructure**

- **Docker Compose** - Containerized development environment
- **Alembic** - Database schema migrations with version control
- **Loguru** - Advanced structured logging with rotation and filtering
- **Pytest** - Comprehensive testing framework with async support
- **Ruff** - High-performance Python linting and formatting

### **Frontend**

- **React 19** - Modern UI library with hooks and concurrent features
- **TypeScript** - Type-safe JavaScript with static analysis
- **Vite** - Fast development server and optimized production builds
- **Tailwind CSS v4** - Utility-first CSS with CSS-native configuration
- **SWR** - Stale-while-revalidate data fetching with polling support

## 🚀 Quick Start

### Prerequisites

Ensure you have the following installed on your system:

- **Python 3.13+**
- **Docker & Docker Compose** (For infrastructure services)
- **UV Package Manager**
- **Git** (For version control)

For the optional web UI:

- **Node.js 20+**
- **npm** (comes with Node.js)

#### Optional

- **GitHub Personal Access Token** ([Create here](https://github.com/settings/tokens)) - For private repositories and higher rate limits
- **OpenAI API Key** ([Get yours here](https://platform.openai.com/api-keys)) - For using GPT instead of pollinations.ai

### 1. Clone & Environment Setup

```bash
# Clone the repository
git clone https://github.com/zingzy/code-review-agent.git
cd code-review-agent

# Install all dependencies with UV
uv sync

# Copy environment template and configure
cp .env.example .env
```

### 2. Environment Configuration

Edit your `.env` file with appropriate values:

```env
# Database Configuration (Docker services)
DATABASE_URL=postgresql://postgres:postgres@localhost:5433/code_review
REDIS_URL=redis://localhost:6379/0

# Celery Task Queue
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

# GitHub Integration (Optional but recommended)
GITHUB_TOKEN=ghp_your_github_token_here

# AI Analysis (Choose your provider)
OPENAI_API_KEY=sk-your_openai_api_key_here

# Security (Generate secure keys)
SECRET_KEY=your-secure-secret-key-here
API_KEY=your-api-authentication-key

# Environment
ENVIRONMENT=development  # development, staging, production
```

#### 🔐 Security Key Generation

Generate secure keys for production:

```bash
# Generate SECRET_KEY
python -c "import secrets; print(f'SECRET_KEY={secrets.token_urlsafe(32)}')"

# Generate API_KEY
python -c "import secrets; print(f'API_KEY={secrets.token_urlsafe(16)}')"
```

### 3. Infrastructure Services

Start the required infrastructure services:

```bash
# Start whole infra
docker-compose up

# Verify services are running
docker-compose ps
```

Wait for services to be healthy, then run database migrations:

```bash
# Initialize database schema
uv run alembic upgrade head
```

## Test the API

### Submit PR Analysis

**POST** `/api/v1/analyze-pr`

Submit a GitHub Pull Request for comprehensive analysis.

**Request Body:**

```json
{
  "repo_url": "https://github.com/owner/repository",
  "pr_number": 123,
  "github_token": "ghp_optional_token_for_private_repos"
}
```

**Response (202 Accepted):**

```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "message": "Analysis task queued successfully",
  "estimated_duration": "2-5 minutes"
}
```

**cURL Example:**

```bash
curl -X POST "http://localhost:8000/api/v1/analyze-pr" \
  -H "Content-Type: application/json" \
  -d '{
    "repo_url": "https://github.com/owner/repo",
    "pr_number": 123,
    "github_token": "optional_token"
  }'
```

### Check Analysis Status

**GET** `/api/v1/status/{task_id}`

Monitor the progress of an analysis task.

**Response Examples:**

```json
{
  "task_id": "uuid-task-id",
  "status": "pending",
  "message": "Analysis task queued successfully"
}
```

**CURL Example:**

```bash
curl "http://localhost:8000/api/v1/status/uuid-task-id"
```

### List Analysis Tasks

**GET** `/api/v1/tasks`

List recent analysis tasks with pagination and optional status filtering.

**Query Parameters:**

- `limit` (int, default 20) - Maximum number of tasks to return
- `offset` (int, default 0) - Number of tasks to skip
- `status_filter` (string, optional) - Filter by status (`pending`, `processing`, `completed`, `failed`, `cancelled`)

**Response (200 OK):**

```json
{
  "tasks": [
    {
      "task_id": "uuid-task-id",
      "status": "completed",
      "repo_url": "https://github.com/owner/repo",
      "pr_number": 123,
      "progress": 100.0,
      "created_at": "2025-09-17T12:01:17.308745"
    }
  ],
  "total_count": 1,
  "has_more": false
}
```

**cURL Example:**

```bash
curl "http://localhost:8000/api/v1/tasks?limit=10&offset=0&status_filter=completed"
```

### Cancel Analysis Task

**DELETE** `/api/v1/tasks/{task_id}`

Cancel a running or pending analysis task.

**Request Body (optional):**

```json
{
  "reason": "User requested cancellation"
}
```

**Response:**

```json
{
  "task_id": "uuid-task-id",
  "status": "cancelled",
  "message": "Task cancelled successfully"
}
```

**cURL Example:**

```bash
curl -X DELETE "http://localhost:8000/api/v1/tasks/uuid-task-id" \
  -H "Content-Type: application/json" \
  -d '{"reason": "User requested cancellation"}'
```

### Get Analysis Results

**GET** `/api/v1/results/{task_id}`

**Response (200 OK):**

```json
{
  "task_id": "uuid-task-id",
  "status": "completed",
  "progress": 100.0,
  "files": [
    {
      "name": "main.py",
      "path": "src/main.py",
      "language": "python",
      "size": 2048,
      "issues": [
        {
          "type": "security",
          "severity": "high",
          "line": 42,
          "description": "Potential SQL injection vulnerability.",
          "suggestion": "Use parameterized queries.",
          "confidence": 0.95
        }
      ]
    }
  ],
    "summary": {
        "total_files": 1,
        "total_issues": 1,
        "critical_issues": 0,
        "high_issues": 1,
        "medium_issues": 0,
        "low_issues": 0,
        "style_issues": 0,
        "bug_issues": 0,
        "performance_issues": 0,
        "security_issues": 0,
        "maintainability_issues": 0,
        "best_practice_issues": 0,
        "code_quality_score": 0.0,
        "maintainability_score": 0.0
    },
    "created_at": "2025-09-17T12:01:17.308745",
    "started_at": "2025-09-17T12:01:17.940944",
    "completed_at": "2025-09-17T12:01:40.288990",
    "analysis_duration": 22.348046,
    "error_message": null
}
```

**CURL Example:**

```bash
curl "http://localhost:8000/api/v1/results/uuid-task-id"
```

## 🎨 Frontend Development

A React-based web UI is available in the `frontend/` directory for interactively submitting PRs, monitoring tasks, and viewing analysis results.

### Setup

```bash
# Install frontend dependencies
make frontend-install

# Or run directly in the frontend folder
cd frontend && npm install
```

### Running the Dev Server

```bash
# Start the frontend on http://localhost:3000
make frontend-dev
```

The Vite dev server proxies `/api/*` requests to `http://localhost:8000`, so the backend must be running.

### Building for Production

```bash
make frontend-build
```

### Verifying the API Contract

A curl-based verification script covers the main API flows used by the frontend:

```bash
bash frontend/scripts/verify.sh
```

Expected output: all checks pass (health, validation error, submit, list, status, cancel).

### Frontend Project Structure

```bash
frontend/
├── public/              # Static assets
├── scripts/
│   └── verify.sh        # API contract verification script
├── src/
│   ├── components/      # UI components (forms, lists, cards, panels)
│   ├── components/ui/   # Reusable primitives (Button, Input, Badge, etc.)
│   ├── hooks/           # SWR data-fetching hooks
│   ├── services/        # Typed API client
│   ├── types/           # TypeScript API types
│   ├── App.tsx          # Dashboard layout
│   └── main.tsx         # Application entry point
├── index.html
├── package.json
├── tsconfig.json
└── vite.config.ts
```

## 🌐 Live Testing

The Code Reviewer Agent is deployed and available for live testing at **https://code-review.spoo.me**.

### Quick Start with Sample PR

Try the service using our sample PR from the URL shortener project:

#### 1. Start Analysis Task

**Submit a PR for analysis:**

```bash
curl -X POST "https://code-review.spoo.me/api/v1/analyze-pr" \
  -H "Content-Type: application/json" \
  -d '{
    "repo_url": "https://github.com/spoo-me/url-shortener",
    "pr_number": 79,
    "github_token": "ghp_your_github_token_here"
  }'
```

> **💡 Tip**: It's highly recommended to pass your own GitHub access token in the request. This provides more relaxed rate limits and ensures better service reliability, especially for private repositories or when the public rate limit is exhausted.

**Expected Response:**

```json
{
  "task_id": "uuid-task-id",
  "status": "pending",
  "message": "Analysis task queued successfully",
  "estimated_duration": "2-5 minutes"
}
```

#### 2. Check Analysis Status

**Monitor your task progress using the returned Task ID:**

```bash
curl "https://code-review.spoo.me/api/v1/status/uuid-task-id"
```

**Response Examples:**

```json
// Initial status
{
  "task_id": "uuid-task-id",
  "status": "pending",
  "message": "Analysis task queued successfully"
}

// In progress
{
  "task_id": "uuid-task-id",
  "status": "in_progress",
  "progress": 45.0,
  "message": "Analyzing file: src/components/Dashboard.tsx"
}

// Completed
{
  "task_id": "uuid-task-id",
  "status": "completed", 
  "progress": 100.0,
  "message": "Analysis completed successfully"
}
```

#### 3. Get Analysis Results

**Retrieve the comprehensive analysis report using the Task ID:**

```bash
curl "https://code-review.spoo.me/api/v1/results/uuid-task-id"
```

**Example Response:**

```json
{
  "task_id": "uuid-task-id",
  "status": "completed",
  "progress": 100.0,
  "files": [
    {
      "name": "main.py",
      "path": "src/main.py",
      "language": "python",
      "size": 2048,
      "issues": [
        {
          "type": "security",
          "severity": "high",
          "line": 42,
          "description": "Potential SQL injection vulnerability.",
          "suggestion": "Use parameterized queries.",
          "confidence": 0.95
        }
      ]
    }
  ],
    "summary": {
        "total_files": 1,
        "total_issues": 1,
        "critical_issues": 0,
        "high_issues": 1,
        "medium_issues": 0,
        "low_issues": 0,
        "style_issues": 0,
        "bug_issues": 0,
        "performance_issues": 0,
        "security_issues": 0,
        "maintainability_issues": 0,
        "best_practice_issues": 0,
        "code_quality_score": 0.0,
        "maintainability_score": 0.0
    },
    "created_at": "2025-09-17T12:01:17.308745",
    "started_at": "2025-09-17T12:01:17.940944",
    "completed_at": "2025-09-17T12:01:40.288990",
    "analysis_duration": 22.348046,
    "error_message": null
}
```

### Additional API Endpoints

#### Cancel Running Task

```bash
curl -X POST "https://code-review.spoo.me/api/v1/cancel/uuid-task-id"
```

#### Analyze Your Own PR

Replace the sample values with your repository details:

```bash
curl -X POST "https://code-review.spoo.me/api/v1/analyze-pr" \
  -H "Content-Type: application/json" \
  -d '{
    "repo_url": "https://github.com/your-username/your-repo",
    "pr_number": <your-pr-number>,
    "github_token": "ghp_your_github_token_here"
  }'
```

### GitHub Token Setup

To get your GitHub personal access token:

1. Go to [GitHub Settings > Developer settings > Personal access tokens](https://github.com/settings/tokens)
2. Click "Generate new token (classic)"
3. Select scopes: `repo` (for private repos) or `public_repo` (for public repos only)
4. Copy the generated token and use it in the `github_token` field

## 🧪 Development & Testing

### Testing Infrastructure

The project maintains a comprehensive test suite with multiple test categories:

```bash
# Run full test suite
uv run pytest

# Run with coverage reporting
uv run pytest --cov=app --cov-report=html --cov-report=term-missing
```

### Code Quality Tools

```bash
# Code formatting with Ruff
uvx ruff format

# Linting and style checks
uvx ruff check
uvx ruff check --fix      # Auto-fix issues

```

### Database Testing

```bash
# Create migration
uv run alembic revision --autogenerate -m "description"

# Apply migrations
uv run alembic upgrade head

# Rollback migration
uv run alembic downgrade -1
```

## 🏗️ Design Decisions & Architecture

### Core Technology Choices

#### **UV vs. pip/poetry**

- **Why UV**: 10-100x faster dependency resolution and installation
- **Benefits**: Unified tool for dependencies, virtual environments, and Python versions

#### **SQLModel vs. SQLAlchemy**

- **Why SQLModel**: Type-safe ORM with Pydantic integration
- **Benefits**: Automatic API serialization, unified data models
- **Trade-offs**: Less mature than pure SQLAlchemy
- **Performance**: Comparable to SQLAlchemy with better developer experience

#### **Celery vs. ARQ/TaskIQ**

- **Current**: Celery for mature ecosystem and Redis integration
- **Benefits**: Battle-tested, extensive monitoring, complex workflows, task cancellation support
- **Trade-offs**: Heavier weight, not async-native
- **Future**: Migration to ARQ planned (see Future Improvements)

#### **LangGraph vs. LangChain**

- **Why LangGraph**: State-based AI workflows
- **Benefits**: Visual workflow representation, cyclic graph support
- **Trade-offs**: Newer, smaller ecosystem
- **Use Case**: Perfect for multi-step code analysis workflows

## 🚀 Future Improvements

- Fully async Task Queue using Arq/TaskIQ
- Fully async redis client for github repo caching using async-redis
- Better tools for more robust code analysis
- Direct Github PR comment bot

## 📂 Project Structure

```bash
code_reviewer_agent/
├── app/                 # FastAPI backend
│   ├── agents/          # AI workflow logic
│   │   ├── ai_workflow.py
│   │   ├── analyzer.py
│   │   └── tools/       # Analysis tools
│   ├── api/             # FastAPI routes
│   │   └── v1/endpoints/
│   ├── config/          # Configuration management
│   ├── models/          # Database & API models
│   ├── services/        # Business logic
│   │   ├── github.py
│   │   └── llm_service.py
│   ├── tasks/           # Celery tasks
│   └── utils/           # Utilities
├── frontend/            # React + TypeScript web UI
│   ├── scripts/         # API verification scripts
│   ├── src/             # Components, hooks, types, API client
│   ├── index.html
│   └── package.json
├── tests/               # Test suite
│   ├── fixtures/        # Test fixtures
│   ├── integration/     # Integration tests
│   └── unit/           # Unit tests
├── migrations/          # Database migrations
├── Makefile            # Convenience commands (frontend-dev, etc.)
└── docs/               # Documentation
```

## 🔍 Analysis Features

### **Code Issues Detected**

- 🔒 **Security vulnerabilities**
- 🐛 **Potential bugs**
- ⚡ **Performance problems**
- 🎨 **Style violations**
- 🔧 **Maintainability concerns**

### **AI Capabilities**

- Context-aware analysis
- Intelligent prioritization
- Detailed explanations
- Fix suggestions

## 🤝 Contributing

1. **Fork** the repository
2. **Create** a feature branch (`git checkout -b feature/amazing-feature`)
3. **Commit** your changes (`git commit -m 'Add amazing feature'`)
4. **Push** to the branch (`git push origin feature/amazing-feature`)
5. **Open** a Pull Request

### 🛠️ Development Guidelines

- Write tests for new features
- Follow existing code style
- Update documentation
- Ensure all tests pass

## 📊 Monitoring

### **Logs**

- Application logs: `logs/app.log`
- Structured JSON logging with Loguru
- Configurable log levels

## 🙏 Acknowledgments

- **FastAPI** for the excellent async framework
- **LangGraph** for AI workflow orchestration
- **OpenAI** for language model capabilities
- **GitHub** for comprehensive API access

---

<h6 align="center">
<img src="https://avatars.githubusercontent.com/u/90309290?v=4" height=30 title="zingzy Copyright">
<br>
© zingzy . 2025

All Rights Reserved</h6>

<p align="center">
	<a href="https://github.com/zingzy/code-review-agent/blob/master/LICENSE"><img src="https://img.shields.io/static/v1.svg?style=for-the-badge&label=License&message=APACHE-2.0&logoColor=d9e0ee&colorA=363a4f&colorB=b7bdf8"/></a>
