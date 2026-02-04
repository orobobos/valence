#!/usr/bin/env python3
"""
Valence CLI - Personal knowledge substrate for AI agents.

Commands:
  valence init              Initialize database (creates schema)
  valence add <content>     Add a new belief
  valence query <text>      Search beliefs with derivation chains
  valence list              List recent beliefs
  valence conflicts         Detect contradicting beliefs
  valence stats             Show database statistics
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

# Try to load .env from common locations
for env_path in [Path.cwd() / '.env', Path.home() / '.valence' / '.env']:
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ.setdefault(key.strip(), value.strip())
        break


def get_db_connection():
    """Get database connection using environment variables."""
    import psycopg2
    from psycopg2.extras import RealDictCursor
    
    return psycopg2.connect(
        host=os.environ.get('VKB_DB_HOST', os.environ.get('PGHOST', 'localhost')),
        port=int(os.environ.get('VKB_DB_PORT', os.environ.get('PGPORT', '5432'))),
        dbname=os.environ.get('VKB_DB_NAME', os.environ.get('PGDATABASE', 'valence')),
        user=os.environ.get('VKB_DB_USER', os.environ.get('PGUSER', 'valence')),
        password=os.environ.get('VKB_DB_PASSWORD', os.environ.get('PGPASSWORD', '')),
        cursor_factory=RealDictCursor,
    )


def get_embedding(text: str) -> list[float] | None:
    """Generate embedding using OpenAI."""
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        return None
    
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        response = client.embeddings.create(
            model='text-embedding-3-small',
            input=text
        )
        return response.data[0].embedding
    except Exception as e:
        print(f"⚠️  Embedding failed: {e}", file=sys.stderr)
        return None


def format_confidence(conf: dict) -> str:
    """Format confidence for display."""
    if not conf:
        return "?"
    overall = conf.get('overall', 0)
    if isinstance(overall, (int, float)):
        return f"{overall:.0%}"
    return str(overall)[:5]


def format_age(dt: datetime) -> str:
    """Format datetime as human-readable age."""
    if not dt:
        return "?"
    
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    
    now = datetime.now(timezone.utc)
    delta = now - dt
    
    if delta.days > 365:
        return f"{delta.days // 365}y"
    elif delta.days > 30:
        return f"{delta.days // 30}mo"
    elif delta.days > 0:
        return f"{delta.days}d"
    elif delta.seconds > 3600:
        return f"{delta.seconds // 3600}h"
    elif delta.seconds > 60:
        return f"{delta.seconds // 60}m"
    else:
        return "now"


# ============================================================================
# INIT Command
# ============================================================================

def cmd_init(args: argparse.Namespace) -> int:
    """Initialize valence database."""
    import psycopg2
    
    print("🔧 Initializing Valence database...")
    
    # Check if we need to create the database
    db_name = os.environ.get('VKB_DB_NAME', 'valence')
    db_host = os.environ.get('VKB_DB_HOST', 'localhost')
    db_port = os.environ.get('VKB_DB_PORT', '5432')
    db_user = os.environ.get('VKB_DB_USER', 'valence')
    db_pass = os.environ.get('VKB_DB_PASSWORD', '')
    
    # First, try to connect to the database
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Check if beliefs table exists
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'beliefs'
            )
        """)
        exists = cur.fetchone()['exists']
        
        if exists and not args.force:
            print(f"✅ Database already initialized at {db_host}:{db_port}/{db_name}")
            cur.execute("SELECT COUNT(*) as count FROM beliefs")
            count = cur.fetchone()['count']
            print(f"   📊 {count} beliefs stored")
            conn.close()
            return 0
        
        conn.close()
    except psycopg2.OperationalError as e:
        print(f"⚠️  Cannot connect to database: {e}")
        print(f"\nTo create a new database, run:")
        print(f"  createdb -h {db_host} -p {db_port} -U {db_user} {db_name}")
        print(f"  # Or with Docker:")
        print(f"  docker run -d --name valence-db -e POSTGRES_USER={db_user} \\")
        print(f"    -e POSTGRES_PASSWORD={db_pass or 'valence'} -e POSTGRES_DB={db_name} \\")
        print(f"    -p {db_port}:5432 pgvector/pgvector:pg16")
        return 1
    
    print("🔨 Creating schema...")
    
    # Read and execute schema
    schema_dir = Path(__file__).parent.parent / 'substrate'
    migrations_dir = Path(__file__).parent.parent.parent.parent / 'migrations'
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Enable required extensions
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        
        # Create core tables if they don't exist
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sources (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                type TEXT NOT NULL,
                title TEXT,
                url TEXT,
                content_hash TEXT,
                session_id UUID,
                metadata JSONB DEFAULT '{}',
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS beliefs (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                content TEXT NOT NULL,
                content_hash CHAR(64),
                embedding vector(1536),
                confidence JSONB DEFAULT '{"overall": 0.7}',
                domain_path TEXT[] DEFAULT '{}',
                source_id UUID REFERENCES sources(id),
                extraction_method TEXT,
                valid_from TIMESTAMPTZ,
                valid_until TIMESTAMPTZ,
                supersedes_id UUID REFERENCES beliefs(id),
                superseded_by_id UUID REFERENCES beliefs(id),
                status TEXT DEFAULT 'active',
                holder_id UUID DEFAULT '00000000-0000-0000-0000-000000000001',
                visibility TEXT DEFAULT 'private',
                version INTEGER DEFAULT 1,
                is_local BOOLEAN DEFAULT TRUE,
                corroboration_count INTEGER DEFAULT 0,
                corroborating_sources JSONB DEFAULT '[]',
                confidence_source REAL DEFAULT 0.5,
                confidence_method REAL DEFAULT 0.5,
                confidence_consistency REAL DEFAULT 1.0,
                confidence_freshness REAL DEFAULT 1.0,
                confidence_corroboration REAL DEFAULT 0.1,
                confidence_applicability REAL DEFAULT 0.8,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                modified_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS entities (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                description TEXT,
                aliases TEXT[] DEFAULT '{}',
                canonical_id UUID REFERENCES entities(id),
                created_at TIMESTAMPTZ DEFAULT NOW(),
                modified_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        
        # Partial unique index for non-aliased entities
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_name_type_unique 
            ON entities(name, type) WHERE canonical_id IS NULL
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS belief_entities (
                belief_id UUID REFERENCES beliefs(id) ON DELETE CASCADE,
                entity_id UUID REFERENCES entities(id) ON DELETE CASCADE,
                role TEXT DEFAULT 'subject',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (belief_id, entity_id)
            )
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tensions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                belief_a_id UUID REFERENCES beliefs(id) ON DELETE CASCADE,
                belief_b_id UUID REFERENCES beliefs(id) ON DELETE CASCADE,
                type TEXT DEFAULT 'contradiction',
                description TEXT,
                severity TEXT DEFAULT 'medium',
                status TEXT DEFAULT 'detected',
                resolution TEXT,
                resolved_at TIMESTAMPTZ,
                detected_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS belief_derivations (
                belief_id UUID PRIMARY KEY REFERENCES beliefs(id) ON DELETE CASCADE,
                derivation_type TEXT NOT NULL DEFAULT 'assumption',
                method_description TEXT,
                confidence_rationale TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS derivation_sources (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                belief_id UUID NOT NULL REFERENCES beliefs(id) ON DELETE CASCADE,
                source_belief_id UUID REFERENCES beliefs(id),
                external_ref TEXT,
                contribution_type TEXT DEFAULT 'primary',
                weight REAL DEFAULT 1.0
            )
        """)
        
        # Create indexes
        cur.execute("CREATE INDEX IF NOT EXISTS idx_beliefs_embedding ON beliefs USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_beliefs_status ON beliefs(status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_beliefs_domain ON beliefs USING GIN(domain_path)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_beliefs_created ON beliefs(created_at DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_derivation_sources_belief ON derivation_sources(belief_id)")
        
        # Create text search
        cur.execute("""
            DO $$ BEGIN
                ALTER TABLE beliefs ADD COLUMN content_tsv tsvector
                    GENERATED ALWAYS AS (to_tsvector('english', content)) STORED;
            EXCEPTION WHEN duplicate_column THEN NULL;
            END $$
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_beliefs_tsv ON beliefs USING GIN(content_tsv)")
        
        conn.commit()
        print("✅ Schema created successfully!")
        
        # Show connection info
        print(f"\n📍 Connected to: {db_host}:{db_port}/{db_name}")
        print("\n💡 Quick start:")
        print("   valence add 'Your first belief here' -d general")
        print("   valence query 'search terms'")
        print("   valence list")
        
        return 0
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Schema creation failed: {e}")
        return 1
    finally:
        cur.close()
        conn.close()


# ============================================================================
# ADD Command
# ============================================================================

def cmd_add(args: argparse.Namespace) -> int:
    """Add a new belief."""
    content = args.content
    
    if not content:
        print("❌ Content is required")
        return 1
    
    # Parse confidence
    confidence = {"overall": 0.7}
    if args.confidence:
        try:
            confidence = json.loads(args.confidence)
        except json.JSONDecodeError:
            # Try parsing as simple float
            try:
                confidence = {"overall": float(args.confidence)}
            except ValueError:
                print(f"❌ Invalid confidence: {args.confidence}")
                return 1
    
    # Parse domains
    domains = args.domain or []
    
    # Generate embedding
    embedding = get_embedding(content)
    embedding_str = None
    if embedding:
        embedding_str = f"[{','.join(str(x) for x in embedding)}]"
    
    # Parse derivation info
    derivation_type = args.derivation_type or 'observation'
    derived_from = args.derived_from  # UUID of source belief
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Insert belief
        cur.execute("""
            INSERT INTO beliefs (content, confidence, domain_path, embedding, extraction_method)
            VALUES (%s, %s, %s, %s::vector, %s)
            RETURNING id, created_at
        """, (content, json.dumps(confidence), domains, embedding_str, derivation_type))
        
        row = cur.fetchone()
        belief_id = row['id']
        
        # Add derivation record
        cur.execute("""
            INSERT INTO belief_derivations (belief_id, derivation_type, method_description)
            VALUES (%s, %s, %s)
        """, (belief_id, derivation_type, args.method or None))
        
        # Link derived_from if provided
        if derived_from:
            cur.execute("""
                INSERT INTO derivation_sources (belief_id, source_belief_id, contribution_type)
                VALUES (%s, %s, 'primary')
            """, (belief_id, derived_from))
        
        conn.commit()
        
        print(f"✅ Belief added: {str(belief_id)[:8]}...")
        print(f"   📝 {content[:60]}{'...' if len(content) > 60 else ''}")
        print(f"   🎯 Confidence: {format_confidence(confidence)}")
        if domains:
            print(f"   📁 Domains: {', '.join(domains)}")
        if embedding:
            print(f"   🧠 Embedding: generated")
        else:
            print(f"   ⚠️  No embedding (set OPENAI_API_KEY)")
        
        return 0
        
    except Exception as e:
        print(f"❌ Failed to add belief: {e}")
        return 1
    finally:
        cur.close()
        conn.close()


# ============================================================================
# QUERY Command
# ============================================================================

def cmd_query(args: argparse.Namespace) -> int:
    """Search beliefs with derivation chains visible."""
    query = args.query
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Try semantic search first if we can get an embedding
        embedding = get_embedding(query)
        
        results = []
        
        if embedding:
            embedding_str = f"[{','.join(str(x) for x in embedding)}]"
            
            # Semantic search with derivation info
            cur.execute("""
                WITH ranked AS (
                    SELECT 
                        b.id,
                        b.content,
                        b.confidence,
                        b.domain_path,
                        b.created_at,
                        b.extraction_method,
                        b.supersedes_id,
                        1 - (b.embedding <=> %s::vector) as similarity,
                        d.derivation_type,
                        d.method_description,
                        d.confidence_rationale
                    FROM beliefs b
                    LEFT JOIN belief_derivations d ON d.belief_id = b.id
                    WHERE b.embedding IS NOT NULL
                      AND b.status = 'active'
                      AND b.superseded_by_id IS NULL
                    ORDER BY b.embedding <=> %s::vector
                    LIMIT %s
                )
                SELECT r.*,
                    (SELECT json_agg(json_build_object(
                        'source_belief_id', ds.source_belief_id,
                        'external_ref', ds.external_ref,
                        'contribution_type', ds.contribution_type
                    ))
                    FROM derivation_sources ds 
                    WHERE ds.belief_id = r.id) as derivation_sources
                FROM ranked r
                WHERE r.similarity >= %s
            """, (embedding_str, embedding_str, args.limit, args.threshold))
            
            results = cur.fetchall()
        
        # Fallback to text search if no embedding or no results
        if not results:
            cur.execute("""
                SELECT 
                    b.id,
                    b.content,
                    b.confidence,
                    b.domain_path,
                    b.created_at,
                    b.extraction_method,
                    b.supersedes_id,
                    ts_rank(b.content_tsv, websearch_to_tsquery('english', %s)) as similarity,
                    d.derivation_type,
                    d.method_description,
                    d.confidence_rationale,
                    (SELECT json_agg(json_build_object(
                        'source_belief_id', ds.source_belief_id,
                        'external_ref', ds.external_ref,
                        'contribution_type', ds.contribution_type
                    ))
                    FROM derivation_sources ds 
                    WHERE ds.belief_id = b.id) as derivation_sources
                FROM beliefs b
                LEFT JOIN belief_derivations d ON d.belief_id = b.id
                WHERE b.content_tsv @@ websearch_to_tsquery('english', %s)
                  AND b.status = 'active'
                  AND b.superseded_by_id IS NULL
                ORDER BY ts_rank(b.content_tsv, websearch_to_tsquery('english', %s)) DESC
                LIMIT %s
            """, (query, query, query, args.limit))
            
            results = cur.fetchall()
        
        # Domain filter
        if args.domain:
            results = [r for r in results if args.domain in (r.get('domain_path') or [])]
        
        if not results:
            print(f"🔍 No beliefs found for: {query}")
            return 0
        
        print(f"🔍 Found {len(results)} belief(s) for: {query}\n")
        
        for i, r in enumerate(results, 1):
            sim = r.get('similarity', 0)
            sim_pct = f"{sim:.0%}" if isinstance(sim, float) else "?"
            
            # Header
            print(f"{'─' * 60}")
            print(f"[{i}] {r['content'][:70]}{'...' if len(r['content']) > 70 else ''}")
            print(f"    ID: {str(r['id'])[:8]}  Confidence: {format_confidence(r.get('confidence', {}))}  Similarity: {sim_pct}  Age: {format_age(r.get('created_at'))}")
            
            if r.get('domain_path'):
                print(f"    Domains: {', '.join(r['domain_path'])}")
            
            # === DERIVATION CHAIN ===
            derivation_type = r.get('derivation_type') or r.get('extraction_method') or 'unknown'
            print(f"    ┌─ Derivation: {derivation_type}")
            
            if r.get('method_description'):
                print(f"    │  Method: {r['method_description']}")
            
            if r.get('confidence_rationale'):
                print(f"    │  Rationale: {r['confidence_rationale']}")
            
            # Show source beliefs
            sources = r.get('derivation_sources') or []
            if sources:
                for src in sources:
                    if src.get('source_belief_id'):
                        # Fetch source belief content
                        cur.execute("SELECT content FROM beliefs WHERE id = %s", (src['source_belief_id'],))
                        src_row = cur.fetchone()
                        src_content = src_row['content'][:50] if src_row else '?'
                        print(f"    │  ← Derived from ({src.get('contribution_type', 'primary')}): {src_content}...")
                    elif src.get('external_ref'):
                        print(f"    │  ← External: {src['external_ref']}")
            
            # Show supersession chain if exists
            if r.get('supersedes_id'):
                print(f"    │  ⟳ Supersedes: {str(r['supersedes_id'])[:8]}...")
                # Optionally walk the chain
                if args.chain:
                    chain = []
                    current = r['supersedes_id']
                    depth = 0
                    while current and depth < 5:
                        cur.execute("SELECT id, content, supersedes_id FROM beliefs WHERE id = %s", (current,))
                        chain_row = cur.fetchone()
                        if chain_row:
                            chain.append(f"{chain_row['content'][:40]}...")
                            current = chain_row['supersedes_id']
                            depth += 1
                        else:
                            break
                    for j, c in enumerate(chain):
                        print(f"    │    {'└' if j == len(chain)-1 else '├'}─ {c}")
            
            print(f"    └─")
        
        print(f"{'─' * 60}")
        
        return 0
        
    except Exception as e:
        print(f"❌ Query failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        cur.close()
        conn.close()


# ============================================================================
# LIST Command
# ============================================================================

def cmd_list(args: argparse.Namespace) -> int:
    """List recent beliefs."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        sql = """
            SELECT 
                b.id,
                b.content,
                b.confidence,
                b.domain_path,
                b.created_at,
                d.derivation_type
            FROM beliefs b
            LEFT JOIN belief_derivations d ON d.belief_id = b.id
            WHERE b.status = 'active'
              AND b.superseded_by_id IS NULL
        """
        params = []
        
        if args.domain:
            sql += " AND %s = ANY(b.domain_path)"
            params.append(args.domain)
        
        sql += " ORDER BY b.created_at DESC LIMIT %s"
        params.append(args.limit)
        
        cur.execute(sql, params)
        results = cur.fetchall()
        
        if not results:
            print("📭 No beliefs found")
            return 0
        
        print(f"📚 {len(results)} belief(s)" + (f" in domain '{args.domain}'" if args.domain else "") + "\n")
        
        for r in results:
            conf = format_confidence(r.get('confidence', {}))
            age = format_age(r.get('created_at'))
            deriv_raw = r.get('derivation_type') or '?'
            deriv = deriv_raw[:6] if deriv_raw else '?'
            content = r['content'][:55] + '...' if len(r['content']) > 55 else r['content']
            
            print(f"  {str(r['id'])[:8]}  [{conf:>4}] [{age:>3}] [{deriv:>6}]  {content}")
        
        return 0
        
    except Exception as e:
        print(f"❌ List failed: {e}")
        return 1
    finally:
        cur.close()
        conn.close()


# ============================================================================
# CONFLICTS Command
# ============================================================================

def cmd_conflicts(args: argparse.Namespace) -> int:
    """Detect beliefs that may contradict each other.
    
    Uses semantic similarity > threshold combined with:
    - Opposite sentiment signals (negation words)
    - Different conclusions about same entities
    """
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        threshold = args.threshold
        
        print(f"🔍 Scanning for conflicts (similarity > {threshold:.0%})...\n")
        
        # Find pairs of beliefs with high semantic similarity
        # that might be contradictions
        cur.execute("""
            WITH belief_pairs AS (
                SELECT 
                    b1.id as id_a,
                    b1.content as content_a,
                    b1.confidence as confidence_a,
                    b1.created_at as created_a,
                    b2.id as id_b,
                    b2.content as content_b,
                    b2.confidence as confidence_b,
                    b2.created_at as created_b,
                    1 - (b1.embedding <=> b2.embedding) as similarity
                FROM beliefs b1
                CROSS JOIN beliefs b2
                WHERE b1.id < b2.id
                  AND b1.embedding IS NOT NULL
                  AND b2.embedding IS NOT NULL
                  AND b1.status = 'active'
                  AND b2.status = 'active'
                  AND b1.superseded_by_id IS NULL
                  AND b2.superseded_by_id IS NULL
                  AND 1 - (b1.embedding <=> b2.embedding) > %s
                ORDER BY similarity DESC
                LIMIT 50
            )
            SELECT * FROM belief_pairs
            WHERE NOT EXISTS (
                SELECT 1 FROM tensions t 
                WHERE (t.belief_a_id = belief_pairs.id_a AND t.belief_b_id = belief_pairs.id_b)
                   OR (t.belief_a_id = belief_pairs.id_b AND t.belief_b_id = belief_pairs.id_a)
            )
        """, (threshold,))
        
        pairs = cur.fetchall()
        
        if not pairs:
            print("✅ No potential conflicts detected")
            return 0
        
        # Analyze each pair for contradiction signals
        conflicts = []
        negation_words = {'not', 'never', 'no', "n't", 'cannot', 'without', 'neither', 
                         'none', 'nobody', 'nothing', 'nowhere', 'false', 'incorrect',
                         'wrong', 'fail', 'reject', 'deny', 'refuse', 'avoid'}
        
        for pair in pairs:
            content_a = pair['content_a'].lower()
            content_b = pair['content_b'].lower()
            
            words_a = set(content_a.split())
            words_b = set(content_b.split())
            
            # Check for negation asymmetry
            neg_a = bool(words_a & negation_words)
            neg_b = bool(words_b & negation_words)
            
            # Higher conflict score if one has negation and other doesn't
            conflict_signal = 0.0
            reason = []
            
            if neg_a != neg_b:
                conflict_signal += 0.4
                reason.append("negation asymmetry")
            
            # Check for opposite conclusions (simple heuristic)
            # e.g., "X is good" vs "X is bad"
            opposites = [
                ('good', 'bad'), ('right', 'wrong'), ('true', 'false'),
                ('should', 'should not'), ('always', 'never'), ('prefer', 'avoid'),
                ('like', 'dislike'), ('works', 'fails'), ('correct', 'incorrect'),
            ]
            
            for pos, neg in opposites:
                if (pos in content_a and neg in content_b) or (neg in content_a and pos in content_b):
                    conflict_signal += 0.3
                    reason.append(f"opposite: {pos}/{neg}")
                    break
            
            # High similarity + some conflict signal = potential contradiction
            if conflict_signal > 0.2 or pair['similarity'] > 0.92:
                conflicts.append({
                    **pair,
                    'conflict_score': conflict_signal + (pair['similarity'] - threshold) * 0.5,
                    'reason': ', '.join(reason) if reason else 'high similarity'
                })
        
        if not conflicts:
            print("✅ Found similar beliefs but no likely contradictions")
            return 0
        
        # Sort by conflict score
        conflicts.sort(key=lambda x: x['conflict_score'], reverse=True)
        
        print(f"⚠️  Found {len(conflicts)} potential conflict(s):\n")
        
        for i, c in enumerate(conflicts[:10], 1):
            print(f"{'═' * 60}")
            print(f"Conflict #{i} (similarity: {c['similarity']:.1%}, signal: {c['conflict_score']:.2f})")
            print(f"Reason: {c['reason']}")
            print()
            print(f"  A [{str(c['id_a'])[:8]}] {c['content_a'][:70]}...")
            print(f"  B [{str(c['id_b'])[:8]}] {c['content_b'][:70]}...")
            print()
            
            if args.auto_record:
                # Record as tension
                cur.execute("""
                    INSERT INTO tensions (belief_a_id, belief_b_id, type, description, severity)
                    VALUES (%s, %s, 'contradiction', %s, %s)
                    ON CONFLICT DO NOTHING
                    RETURNING id
                """, (
                    c['id_a'], 
                    c['id_b'], 
                    f"Auto-detected: {c['reason']}",
                    'high' if c['conflict_score'] > 0.5 else 'medium'
                ))
                tension_row = cur.fetchone()
                if tension_row:
                    print(f"  📝 Recorded as tension: {str(tension_row['id'])[:8]}")
        
        if args.auto_record:
            conn.commit()
        
        print(f"{'═' * 60}")
        print(f"\n💡 Use 'valence tension resolve <id>' to resolve conflicts")
        
        return 0
        
    except Exception as e:
        print(f"❌ Conflict detection failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        cur.close()
        conn.close()


# ============================================================================
# STATS Command
# ============================================================================

def cmd_stats(args: argparse.Namespace) -> int:
    """Show database statistics."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("SELECT COUNT(*) as total FROM beliefs")
        total = cur.fetchone()['total']
        
        cur.execute("SELECT COUNT(*) as active FROM beliefs WHERE status = 'active' AND superseded_by_id IS NULL")
        active = cur.fetchone()['active']
        
        cur.execute("SELECT COUNT(*) as with_emb FROM beliefs WHERE embedding IS NOT NULL")
        with_embedding = cur.fetchone()['with_emb']
        
        cur.execute("SELECT COUNT(*) as tensions FROM tensions WHERE status = 'detected'")
        tensions = cur.fetchone()['tensions']
        
        try:
            cur.execute("SELECT COUNT(DISTINCT d) as count FROM beliefs, LATERAL unnest(domain_path) as d")
            domains = cur.fetchone()['count']
        except:
            domains = 0
        
        cur.execute("SELECT COUNT(*) as derivations FROM belief_derivations")
        derivations = cur.fetchone()['derivations']
        
        print("📊 Valence Statistics")
        print("─" * 30)
        print(f"  Total beliefs:      {total}")
        print(f"  Active beliefs:     {active}")
        print(f"  With embeddings:    {with_embedding}")
        print(f"  Derivation records: {derivations}")
        print(f"  Unique domains:     {domains}")
        print(f"  Unresolved tensions:{tensions}")
        
        return 0
        
    except Exception as e:
        print(f"❌ Stats failed: {e}")
        return 1
    finally:
        cur.close()
        conn.close()


# ============================================================================
# Main Entry Point
# ============================================================================

def app() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog='valence',
        description='Personal knowledge substrate for AI agents',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  valence init                      Initialize database
  valence add "Fact here" -d tech   Add belief with domain
  valence query "search terms"      Search with derivation chains
  valence list -n 20                List recent beliefs
  valence conflicts                 Detect contradictions
  valence stats                     Show statistics
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', required=True)
    
    # init
    init_parser = subparsers.add_parser('init', help='Initialize database schema')
    init_parser.add_argument('--force', '-f', action='store_true', help='Recreate schema even if exists')
    
    # add
    add_parser = subparsers.add_parser('add', help='Add a new belief')
    add_parser.add_argument('content', help='Belief content')
    add_parser.add_argument('--confidence', '-c', help='Confidence (JSON or float 0-1)')
    add_parser.add_argument('--domain', '-d', action='append', help='Domain tag (repeatable)')
    add_parser.add_argument('--derivation-type', '-t', 
                          choices=['observation', 'inference', 'aggregation', 'hearsay', 'assumption', 'correction', 'synthesis'],
                          default='observation', help='How this belief was derived')
    add_parser.add_argument('--derived-from', help='UUID of source belief this was derived from')
    add_parser.add_argument('--method', '-m', help='Method description for derivation')
    
    # query
    query_parser = subparsers.add_parser('query', help='Search beliefs')
    query_parser.add_argument('query', help='Search query')
    query_parser.add_argument('--limit', '-n', type=int, default=10, help='Max results')
    query_parser.add_argument('--threshold', '-t', type=float, default=0.3, help='Min similarity')
    query_parser.add_argument('--domain', '-d', help='Filter by domain')
    query_parser.add_argument('--chain', action='store_true', help='Show full supersession chains')
    
    # list
    list_parser = subparsers.add_parser('list', help='List recent beliefs')
    list_parser.add_argument('--limit', '-n', type=int, default=10, help='Max results')
    list_parser.add_argument('--domain', '-d', help='Filter by domain')
    
    # conflicts
    conflicts_parser = subparsers.add_parser('conflicts', help='Detect contradicting beliefs')
    conflicts_parser.add_argument('--threshold', '-t', type=float, default=0.85, 
                                 help='Similarity threshold for conflict detection')
    conflicts_parser.add_argument('--auto-record', '-r', action='store_true',
                                 help='Automatically record detected conflicts as tensions')
    
    # stats
    subparsers.add_parser('stats', help='Show database statistics')
    
    return parser


def main() -> int:
    """Main entry point."""
    parser = app()
    args = parser.parse_args()
    
    commands = {
        'init': cmd_init,
        'add': cmd_add,
        'query': cmd_query,
        'list': cmd_list,
        'conflicts': cmd_conflicts,
        'stats': cmd_stats,
    }
    
    handler = commands.get(args.command)
    if handler:
        return handler(args)
    
    parser.print_help()
    return 1


if __name__ == '__main__':
    sys.exit(main())
