"""Database configuration for the demo application."""

from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

# Create async engine with SQLite
engine = create_async_engine(f"sqlite+aiosqlite:///{Path(__file__).parent / 'demo.db'}", echo=False)

# Create async session factory
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncSession:
    """Get an async database session."""
    async with async_session() as session:
        yield session


async def init_db() -> None:
    """Initialize database tables and seed data."""
    from sqlmodel import SQLModel

    from demo.blog.models import Comment, Post, User, UserFavoritePost

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    # Seed initial data
    async with async_session() as session:
        # Check if data already exists
        from sqlmodel import select

        existing = await session.exec(select(User))
        if existing.first():
            return

        # --- Users ---
        users_data = [
            ("Alice", "alice@example.com"),
            ("Bob", "bob@example.com"),
            ("Charlie", "charlie@example.com"),
            ("Diana", "diana@example.com"),
            ("Eve", "eve@example.com"),
            ("Frank", "frank@example.com"),
            ("Grace", "grace@example.com"),
            ("Henry", "henry@example.com"),
        ]
        users: list[User] = []
        for name, email in users_data:
            u = User(name=name, email=email)
            session.add(u)
            users.append(u)
        await session.commit()
        for u in users:
            await session.refresh(u)

        # --- Posts ---
        posts_data = [
            # Alice's posts (10)
            ("Hello World", "My first post!", users[0].id),
            ("GraphQL is Great", "Learning GraphQL with SQLModel", users[0].id),
            ("Async Python Patterns", "asyncio, aiohttp, and more", users[0].id),
            ("Type Hints Best Practices", "Making the most of Python typing", users[0].id),
            ("FastAPI Tips and Tricks", "Building fast APIs with FastAPI", users[0].id),
            ("SQLModel vs SQLAlchemy", "When to use what", users[0].id),
            ("Python 3.12 New Features", "What's new in the latest release", users[0].id),
            ("Deploying with Docker", "Containerizing your Python app", users[0].id),
            ("Testing Async Code", "pytest-asyncio patterns", users[0].id),
            ("Code Review Checklist", "Things to look for when reviewing code", users[0].id),
            # Bob's posts (8)
            ("Python Tips", "Some useful Python tips", users[1].id),
            ("Database Design 101", "Normalization and indexing strategies", users[1].id),
            ("REST API Design", "Best practices for REST endpoints", users[1].id),
            ("Intro to Pydantic", "Data validation made easy", users[1].id),
            ("CI/CD Pipelines", "Automating your deployment workflow", users[1].id),
            ("Git Workflow Strategies", " trunk-based vs feature branches", users[1].id),
            ("Python Logging Guide", "Structured logging for production", users[1].id),
            ("Web Scraping Ethics", "Responsible data collection", users[1].id),
            # Charlie's posts (6)
            ("Machine Learning Basics", "Getting started with scikit-learn", users[2].id),
            ("Data Visualization", "Matplotlib and Seaborn tips", users[2].id),
            ("Pandas Tricks", "Data manipulation shortcuts", users[2].id),
            ("Jupyter Notebook Tips", "Being productive in notebooks", users[2].id),
            ("SQL for Data Analysis", "Window functions and CTEs", users[2].id),
            ("Numpy Performance", "Vectorizing your computations", users[2].id),
            # Diana's posts (5)
            ("Kubernetes Intro", "Container orchestration basics", users[3].id),
            ("Terraform Getting Started", "Infrastructure as code", users[3].id),
            ("AWS Lambda Tips", "Serverless Python patterns", users[3].id),
            ("Monitoring with Grafana", "Dashboards and alerting", users[3].id),
            ("Redis Patterns", "Caching strategies for web apps", users[3].id),
            # Eve's posts (4)
            ("Security Best Practices", "OWASP top 10 for Python devs", users[4].id),
            ("OAuth 2.0 Explained", "Understanding auth flows", users[4].id),
            ("JWT vs Sessions", "When to use which", users[4].id),
            ("HTTPS and TLS", "How encryption works on the web", users[4].id),
            # Frank's posts (4)
            ("Vue.js for Backend Devs", "A practical introduction", users[5].id),
            ("CSS Layout Masterclass", "Flexbox and Grid patterns", users[5].id),
            ("TypeScript Essentials", "Type safety for frontend code", users[5].id),
            ("React Hooks Deep Dive", "useEffect, useMemo, useCallback", users[5].id),
            # Grace's posts (3)
            ("Agile Retrospectives", "Making the most of team reflections", users[6].id),
            ("Technical Writing Tips", "Writing clear documentation", users[6].id),
            ("Open Source Contributions", "Getting started with OSS", users[6].id),
            # Henry's posts (2)
            ("Game Dev with Pygame", "Building a simple game", users[7].id),
            ("Embedded Python", "MicroPython and IoT projects", users[7].id),
        ]
        posts: list[Post] = []
        for title, content, author_id in posts_data:
            p = Post(title=title, content=content, author_id=author_id)
            session.add(p)
            posts.append(p)
        await session.commit()
        for p in posts:
            await session.refresh(p)

        # --- Comments (3-5 per post) ---
        comment_templates = [
            "Great post!",
            "Thanks for sharing!",
            "Very helpful, bookmarked.",
            "Looking forward to the next one.",
            "Could you elaborate on the third point?",
            "I disagree with some of this, but good overview.",
            "This saved me hours of debugging.",
            "Solid explanation, thanks.",
            "Would love to see a follow-up post.",
            "Nice write-up, shared with my team.",
        ]
        comments: list[Comment] = []
        for i, post in enumerate(posts):
            # 3-5 comments per post, cycling through other users as authors
            n_comments = 3 + (i % 3)
            for j in range(n_comments):
                author = users[(i + j + 1) % len(users)]
                text = comment_templates[(i * 3 + j) % len(comment_templates)]
                c = Comment(content=text, post_id=post.id, author_id=author.id)
                session.add(c)
                comments.append(c)
        await session.commit()

        # --- Favorites (users favorite 3-6 posts) ---
        import random

        rng = random.Random(42)  # deterministic seed
        for user in users:
            # Each user favorites 3-6 random posts
            n_favs = 3 + rng.randint(0, 3)
            fav_post_ids = rng.sample([p.id for p in posts], min(n_favs, len(posts)))
            for pid in fav_post_ids:
                f = UserFavoritePost(user_id=user.id, post_id=pid)
                session.add(f)
        await session.commit()
