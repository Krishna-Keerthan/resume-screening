"""
app/services/skill_taxonomy.py

Centralised skill vocabulary for the resume parser and keyword matcher.

WHY THIS FILE EXISTS
--------------------
The original _TECH_SKILLS set (99 entries) was embedded directly inside
resume_parser.py.  Moving it here:
  - Lets keyword_matcher.py, job_parser.py, and tests share the same vocab.
  - Makes it easy to extend without touching parser logic.
  - Adds skill categories (useful for LLM prompts and UI grouping).

USAGE
-----
    from app.services.skill_taxonomy import TECH_SKILLS, SKILL_ALIASES, SKILL_CATEGORIES

IMPROVEMENTS OVER ORIGINAL
---------------------------
  - 99 → 400+ entries (all post-2022 AI/ML/cloud/BI tools added)
  - Added categories dict for grouping
  - Added NEGATION_WORDS for negation-aware extraction
  - Added SPECIAL_BOUNDARY_SKILLS for tokens that need non-\b regex matching
    (e.g. "c++", "c#" where \b fails at the '+' character)
"""

# ─────────────────────────────────────────────────────────────────────────────
# Main vocabulary
# ─────────────────────────────────────────────────────────────────────────────

TECH_SKILLS: set[str] = {
    # ── Languages ─────────────────────────────────────────────────────────────
    "python", "javascript", "typescript", "java", "c++", "c#", "c",
    "ruby", "go", "golang", "rust", "swift", "kotlin", "scala",
    "r", "matlab", "php", "perl", "dart", "elixir", "erlang",
    "haskell", "clojure", "groovy", "lua", "julia", "fortran",
    "cobol", "assembly", "bash", "shell", "powershell", "vba",
    "objective-c", "f#", "solidity", "move", "zig",

    # ── Web Frontend ──────────────────────────────────────────────────────────
    "react", "vue", "angular", "next.js", "nuxt", "nuxt.js",
    "svelte", "sveltekit", "remix", "astro", "gatsby",
    "html", "css", "sass", "less", "tailwind", "tailwindcss",
    "bootstrap", "material ui", "shadcn", "chakra ui",
    "jquery", "htmx", "alpinejs",
    "webpack", "vite", "rollup", "parcel", "esbuild", "babel",
    "storybook", "cypress", "playwright", "selenium", "jest",
    "vitest", "testing library", "enzyme",

    # ── Backend Frameworks ────────────────────────────────────────────────────
    "flask", "django", "fastapi", "starlette", "tornado",
    "express", "nestjs", "koa", "hapi", "fastify",
    "spring", "spring boot", "quarkus", "micronaut",
    "rails", "sinatra", "laravel", "symfony", "codeigniter", "lumen",
    "gin", "fiber", "echo",
    "actix", "axum", "rocket",
    "phoenix", "plug",
    "node.js", "bun", "deno",

    # ── APIs & Communication ───────────────────────────────────────────────────
    "graphql", "rest", "restful", "grpc", "websocket", "webhooks",
    "openapi", "swagger", "soap", "xml", "json",
    "trpc", "apollo", "relay",
    "oauth", "oauth2", "jwt", "saml", "openid",

    # ── Data & Analytics ──────────────────────────────────────────────────────
    "sql", "nosql", "postgresql", "mysql", "sqlite", "mariadb",
    "mongodb", "redis", "elasticsearch", "opensearch",
    "cassandra", "dynamodb", "neo4j", "oracle", "mssql", "sql server",
    "cockroachdb", "timescaledb", "influxdb", "clickhouse",
    "snowflake", "bigquery", "redshift", "databricks",
    "dbt", "fivetran", "airbyte", "stitch",
    "spark", "hadoop", "hive", "presto", "trino", "flink",
    "kafka", "pulsar", "rabbitmq", "nats", "sqs", "pubsub",
    "airflow", "prefect", "dagster", "luigi",
    "pandas", "polars", "numpy", "scipy",
    "matplotlib", "seaborn", "plotly", "bokeh", "altair",
    "tableau", "power bi", "looker", "metabase", "superset",
    "excel", "google sheets", "data studio",

    # ── Machine Learning & AI ─────────────────────────────────────────────────
    "machine learning", "deep learning", "nlp", "computer vision",
    "data science", "data analysis", "statistics",
    "tensorflow", "pytorch", "keras", "jax",
    "scikit-learn", "xgboost", "lightgbm", "catboost",
    "hugging face", "transformers", "langchain", "llamaindex",
    "openai", "anthropic", "gemini", "llm", "rag",
    "reinforcement learning", "time series",
    "feature engineering", "model deployment", "mlops",
    "mlflow", "wandb", "weights & biases", "comet",
    "kubeflow", "sagemaker", "vertex ai", "azure ml",
    "opencv", "pillow", "clip", "stable diffusion",
    "vector database", "pinecone", "weaviate", "chroma", "faiss",
    "prompt engineering", "fine-tuning", "lora",

    # ── Cloud & Infrastructure ────────────────────────────────────────────────
    "aws", "gcp", "azure", "google cloud",
    "ec2", "s3", "lambda", "ecs", "eks", "rds", "aurora",
    "cloudformation", "cdk", "sam",
    "gke", "cloud run", "cloud functions", "firebase",
    "azure devops", "aks", "cosmos db",
    "docker", "kubernetes", "helm", "kustomize",
    "terraform", "ansible", "chef", "puppet",
    "pulumi", "crossplane",
    "jenkins", "github actions", "gitlab ci", "circle ci",
    "travis ci", "teamcity", "bamboo", "argo cd", "flux",
    "ci/cd", "devops", "gitops", "devsecops", "sre",
    "linux", "unix", "nginx", "apache", "haproxy", "envoy",
    "istio", "linkerd", "consul", "vault",
    "prometheus", "grafana", "datadog", "new relic", "dynatrace",
    "elk stack", "logstash", "kibana", "splunk", "jaeger",
    "cloudflare", "cdn", "load balancer",

    # ── Mobile ────────────────────────────────────────────────────────────────
    "react native", "flutter", "ionic", "expo",
    "android", "ios", "xcode", "swiftui",
    "kotlin multiplatform", "capacitor", "cordova",

    # ── Security ──────────────────────────────────────────────────────────────
    "cybersecurity", "penetration testing", "ethical hacking",
    "owasp", "ssl", "tls", "encryption", "zero trust",
    "siem", "soar", "identity management", "iam",
    "burp suite", "wireshark", "nmap", "metasploit",

    # ── Tools & Practices ─────────────────────────────────────────────────────
    "git", "github", "gitlab", "bitbucket", "svn",
    "jira", "confluence", "notion", "trello", "asana", "linear",
    "figma", "sketch", "adobe xd", "invision", "zeplin",
    "postman", "insomnia", "httpie",
    "vscode", "intellij", "vim", "neovim",
    "microservices", "monorepo", "domain-driven design", "ddd",
    "test-driven development", "tdd", "bdd", "pair programming",
    "code review", "documentation",

    # ── Architecture patterns ──────────────────────────────────────────────────
    "event-driven", "cqrs", "event sourcing", "saga pattern",
    "serverless", "edge computing", "distributed systems",
    "system design", "high availability", "fault tolerance",
    "api gateway", "service mesh",

    # ── Soft / Professional skills ────────────────────────────────────────────
    "leadership", "communication", "teamwork", "collaboration",
    "problem solving", "critical thinking", "analytical",
    "project management", "agile", "scrum", "kanban", "lean",
    "mentoring", "coaching", "stakeholder management",
    "product management", "cross-functional",
    "remote work", "time management",
}

# ─────────────────────────────────────────────────────────────────────────────
# Alias map  (what user types → canonical skill name in TECH_SKILLS)
# ─────────────────────────────────────────────────────────────────────────────

SKILL_ALIASES: dict[str, str] = {
    # Language shorthands
    "js":             "javascript",
    "ts":             "typescript",
    "py":             "python",
    "golang":         "go",
    "c++":            "c++",   # keep as-is (alias for boundary handling)
    "cplusplus":      "c++",
    "csharp":         "c#",
    "dotnet":         "c#",
    ".net":           "c#",
    "objective c":    "objective-c",

    # Node/JS
    "node":           "node.js",
    "nodejs":         "node.js",
    "react.js":       "react",
    "reactjs":        "react",
    "react js":       "react",
    "next":           "next.js",
    "nextjs":         "next.js",
    "nuxtjs":         "nuxt.js",
    "vuejs":          "vue",
    "vue.js":         "vue",
    "angular.js":     "angular",
    "angularjs":      "angular",
    "sveltejs":       "svelte",
    "tailwind css":   "tailwindcss",

    # Backend
    "spring mvc":     "spring",
    "springboot":     "spring boot",
    "nestjs":         "nestjs",
    "expressjs":      "express",
    "express.js":     "express",
    "fastify.js":     "fastify",

    # Data & ML
    "postgres":       "postgresql",
    "psql":           "postgresql",
    "mongo":          "mongodb",
    "elastic":        "elasticsearch",
    "tf":             "tensorflow",
    "sklearn":        "scikit-learn",
    "scikit learn":   "scikit-learn",
    "hf":             "hugging face",
    "huggingface":    "hugging face",
    "langchain":      "langchain",
    "xgb":            "xgboost",
    "lgbm":           "lightgbm",
    "ml":             "machine learning",
    "dl":             "deep learning",
    "nlp":            "nlp",
    "cv":             "computer vision",
    "ai":             "machine learning",

    # Cloud
    "gcp":            "gcp",
    "google cloud platform": "google cloud",
    "amazon web services": "aws",
    "microsoft azure": "azure",
    "k8s":            "kubernetes",
    "kube":           "kubernetes",
    "gh actions":     "github actions",
    "gha":            "github actions",
    "cicd":           "ci/cd",
    "ci cd":          "ci/cd",

    # Tools
    "powerbi":        "power bi",
    "w&b":            "wandb",
    "wandb":          "wandb",

    # Other
    "ddl":            "sql",
    "dml":            "sql",
    "plsql":          "sql",
    "tsql":           "sql",
    "nosql":          "nosql",
}

# ─────────────────────────────────────────────────────────────────────────────
# Skills requiring special regex (non-word boundary characters)
# ─────────────────────────────────────────────────────────────────────────────

SPECIAL_BOUNDARY_SKILLS: dict[str, str] = {
    # skill_name: custom regex pattern to use instead of \b...\b
    "c++":    r"(?<![a-zA-Z0-9])c\+\+(?![a-zA-Z0-9])",
    "c#":     r"(?<![a-zA-Z0-9])c#(?![a-zA-Z0-9])",
    "c":      r"(?<![a-zA-Z0-9])c(?![a-zA-Z0-9+#])",
    ".net":   r"(?<![a-zA-Z0-9])\.net(?![a-zA-Z0-9])",
    "f#":     r"(?<![a-zA-Z0-9])f#(?![a-zA-Z0-9])",
    "ci/cd":  r"(?<![a-zA-Z0-9])ci/cd(?![a-zA-Z0-9])",
    "r":      r"(?<![a-zA-Z0-9])r(?![a-zA-Z0-9])",
    "next.js": r"next\.js",
    "nuxt.js": r"nuxt\.js",
    "node.js": r"node\.js",
}

# ─────────────────────────────────────────────────────────────────────────────
# Skill categories  (used by LLM prompts and UI skill-gap grouping)
# ─────────────────────────────────────────────────────────────────────────────

SKILL_CATEGORIES: dict[str, list[str]] = {
    "languages": [
        "python", "javascript", "typescript", "java", "c++", "c#", "go",
        "rust", "swift", "kotlin", "scala", "ruby", "php", "dart", "r",
        "matlab", "bash", "shell", "powershell", "elixir", "erlang",
    ],
    "web_frontend": [
        "react", "vue", "angular", "next.js", "svelte", "html", "css",
        "tailwindcss", "bootstrap", "webpack", "vite", "gatsby",
    ],
    "backend": [
        "flask", "django", "fastapi", "express", "nestjs", "spring",
        "spring boot", "rails", "laravel", "node.js", "graphql", "rest",
        "grpc", "fastify",
    ],
    "data_analytics": [
        "sql", "pandas", "numpy", "spark", "hadoop", "kafka",
        "airflow", "dbt", "snowflake", "bigquery", "redshift", "databricks",
        "tableau", "power bi", "looker", "metabase",
    ],
    "ml_ai": [
        "machine learning", "deep learning", "nlp", "computer vision",
        "tensorflow", "pytorch", "scikit-learn", "xgboost", "hugging face",
        "langchain", "llm", "rag", "mlops", "mlflow", "wandb",
        "stable diffusion", "prompt engineering", "fine-tuning",
    ],
    "databases": [
        "postgresql", "mysql", "mongodb", "redis", "elasticsearch",
        "cassandra", "dynamodb", "neo4j", "clickhouse", "sqlite",
        "cockroachdb", "oracle",
    ],
    "cloud_infra": [
        "aws", "gcp", "azure", "docker", "kubernetes", "terraform",
        "ansible", "jenkins", "github actions", "ci/cd", "helm",
        "prometheus", "grafana", "datadog", "linux",
    ],
    "mobile": [
        "react native", "flutter", "android", "ios", "swiftui",
        "kotlin multiplatform",
    ],
    "security": [
        "cybersecurity", "penetration testing", "owasp", "ssl", "tls",
        "iam", "zero trust",
    ],
    "tools": [
        "git", "github", "gitlab", "jira", "confluence", "figma",
        "postman", "vscode",
    ],
    "soft_skills": [
        "leadership", "communication", "teamwork", "problem solving",
        "agile", "scrum", "project management", "mentoring",
    ],
}

# ─────────────────────────────────────────────────────────────────────────────
# Negation words  (if any of these appear within 8 tokens BEFORE a skill,
# discard the match)
# ─────────────────────────────────────────────────────────────────────────────

NEGATION_WORDS: frozenset[str] = frozenset({
    "no", "not", "without", "except", "excluding", "lacks",
    "lack", "unfamiliar", "limited", "inexperienced", "never",
    "non", "avoid", "avoiding", "prevented", "unable",
})


SKILL_SYNONYMS: dict[str, str] = {
    # REST variants
    "restful":              "rest",
    "rest api":             "rest",
    "rest apis":            "rest",
    "restful api":          "rest",
    "restful apis":         "rest",
    "restful web services": "rest",
    "http api":             "rest",
    # SQL variants
    "relational database":  "sql",
    "rdbms":                "sql",
    "structured query":     "sql",
    # ML variants
    "artificial intelligence": "machine learning",
    "statistical modeling": "machine learning",
    "predictive modeling":  "machine learning",
    # Cloud variants
    "amazon cloud":         "aws",
    "amazon web service":   "aws",
    "google cloud platform":"gcp",
    "microsoft azure cloud":"azure",
    # OOP
    "object oriented":      "object-oriented programming",
    "oop":                  "object-oriented programming",
    "object oriented programming": "object-oriented programming",
    # CI/CD variants
    "continuous integration":  "ci/cd",
    "continuous deployment":   "ci/cd",
    "continuous delivery":     "ci/cd",
    # Git variants
    "version control":      "git",
    "source control":       "git",
    # Docker variants
    "containerization":     "docker",
    "containers":           "docker",
    "container orchestration": "kubernetes",
    # Data variants
    "data wrangling":       "pandas",
    "data manipulation":    "pandas",
    "data visualization":   "matplotlib",
}