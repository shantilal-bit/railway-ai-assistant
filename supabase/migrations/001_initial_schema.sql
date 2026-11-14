-- Indian Railway Rules AI Assistant — Scalable PostgreSQL + pgvector Schema
-- Target: Supabase PostgreSQL 15+

create extension if not exists vector;
create extension if not exists pgcrypto;

-- 1. Railway Zones (Initially Western Railway active; extensible to all 17 Zones + Railway Board)
create table if not exists public.zones (
    id uuid primary key default gen_random_uuid(),
    code text not null unique,                 -- e.g. 'WR', 'CR', 'NR', 'RB'
    name text not null,                        -- e.g. 'Western Railway'
    name_hi text,                              -- e.g. 'पश्चिम रेलवे'
    is_active boolean not null default false,  -- true for WR initially; flip to true to enable others without app rebuild
    is_national_board boolean not null default false,
    sort_order int not null default 100,
    created_at timestamptz not null default now()
);

-- 2. Divisions per Zone
create table if not exists public.divisions (
    id uuid primary key default gen_random_uuid(),
    zone_id uuid not null references public.zones(id) on delete cascade,
    code text not null,                        -- e.g. 'BCT', 'BRC', 'ADI', 'RTM', 'RJT', 'BVP'
    name text not null,
    name_hi text,
    is_active boolean not null default true,
    sort_order int not null default 100,
    created_at timestamptz not null default now(),
    unique (zone_id, code)
);

-- 3. Departments (Global catalog or zone-extensible)
create table if not exists public.departments (
    id uuid primary key default gen_random_uuid(),
    code text not null unique,
    name text not null,
    name_hi text,
    is_active boolean not null default true,
    sort_order int not null default 100,
    created_at timestamptz not null default now()
);

-- 4. User Profiles (extends Supabase auth.users)
create table if not exists public.profiles (
    id uuid primary key references auth.users(id) on delete cascade,
    email text not null,
    full_name text,
    employee_id text,
    role text not null default 'employee' check (role in ('employee', 'reviewer', 'admin')),
    default_zone_id uuid references public.zones(id),
    default_division_id uuid references public.divisions(id),
    default_department_id uuid references public.departments(id),
    preferred_language text not null default 'auto' check (preferred_language in ('auto', 'en', 'hi')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- 5. Official Railway PDF Documents (metadata only; binary PDFs live in Cloudflare R2)
create table if not exists public.documents (
    id uuid primary key default gen_random_uuid(),
    title text not null,                       -- Official document name
    document_number text,                      -- e.g. RBE No. 45/2024, WR Joint Circular No. ...
    document_type text not null check (
        document_type in ('ACT', 'RULE_BOOK', 'MANUAL', 'CIRCULAR', 'JPO', 'AMENDMENT_SLIP', 'GAZETTE', 'OTHER')
    ),
    issuing_authority text not null,           -- e.g. 'Railway Board', 'PCPO Western Railway', 'DRM BCT'
    authority_rank int not null default 50,    -- Higher rank = stronger legal authority (e.g. Railway Board/Act = 100, Zone = 70, Division = 50)
    r2_object_key text not null unique,        -- Cloudflare R2 key, e.g. 'wr/bct/operating/gr_sr_2023.pdf'
    file_sha256 text not null,                 -- Integrity verification
    page_count int,
    language text not null default 'en' check (language in ('en', 'hi', 'bilingual')),
    issue_date date,
    effective_date date,
    requires_ocr boolean not null default false,
    ocr_status text not null default 'not_needed' check (ocr_status in ('not_needed', 'pending', 'completed', 'failed')),
    status text not null default 'draft' check (status in ('draft', 'in_review', 'published', 'superseded', 'disabled')),
    disabled_reason text,
    uploaded_by uuid references public.profiles(id),
    reviewed_by uuid references public.profiles(id),
    published_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- 6. Document Scopes (Supports department, division-wide, zone-wide, Railway Board, or common applicability)
create table if not exists public.document_scopes (
    id uuid primary key default gen_random_uuid(),
    document_id uuid not null references public.documents(id) on delete cascade,
    scope_level text not null check (
        scope_level in ('DEPARTMENT', 'DIVISION', 'ZONE', 'RAILWAY_BOARD', 'COMMON')
    ),
    zone_id uuid references public.zones(id) on delete cascade,
    division_id uuid references public.divisions(id) on delete cascade,
    department_id uuid references public.departments(id) on delete cascade,
    created_at timestamptz not null default now()
);

create index if not exists idx_doc_scopes_lookup
    on public.document_scopes (scope_level, zone_id, division_id, department_id);

-- 7. Extracted & Indexed Rule Chunks (pgvector + FTS)
create table if not exists public.rule_chunks (
    id uuid primary key default gen_random_uuid(),
    document_id uuid not null references public.documents(id) on delete cascade,
    chunk_index int not null,
    page_number int not null,
    rule_number text,                          -- e.g. 'GR 4.10', 'Para 508', 'Rule 3(1)(i)'
    section_title text,
    content text not null,
    content_tsv tsvector generated always as (to_tsvector('english', coalesce(rule_number, '') || ' ' || coalesce(section_title, '') || ' ' || content)) stored,
    embedding vector(1536),
    token_count int,
    created_at timestamptz not null default now(),
    unique (document_id, chunk_index)
);

create index if not exists idx_rule_chunks_doc_page on public.rule_chunks (document_id, page_number);
create index if not exists idx_rule_chunks_tsv on public.rule_chunks using gin (content_tsv);
create index if not exists idx_rule_chunks_embedding on public.rule_chunks using hnsw (embedding vector_cosine_ops);

-- 8. Amendments & Superseded Document Relationships
create table if not exists public.amendments (
    id uuid primary key default gen_random_uuid(),
    amending_document_id uuid not null references public.documents(id) on delete cascade,
    target_document_id uuid not null references public.documents(id) on delete cascade,
    relationship_type text not null check (
        relationship_type in ('AMENDS', 'SUPERSEDES', 'CLARIFIES', 'PARTIALLY_MODIFIES', 'REPEALS')
    ),
    affected_rule_number text,
    circular_reference text,
    effective_date date,
    notes text,
    created_at timestamptz not null default now()
);

-- 9. Chat Sessions & Messages
create table if not exists public.chat_sessions (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references public.profiles(id) on delete cascade,
    zone_id uuid not null references public.zones(id),
    division_id uuid not null references public.divisions(id),
    department_id uuid not null references public.departments(id),
    title text not null default 'New Railway Rule Query',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.chat_messages (
    id uuid primary key default gen_random_uuid(),
    session_id uuid not null references public.chat_sessions(id) on delete cascade,
    role text not null check (role in ('user', 'assistant')),
    language text not null default 'en',
    content text not null,
    structured_answer jsonb,                   -- Stores the 7-part structured response + citations + conflicts
    ai_provider text,                          -- 'groq', 'openai', 'gemini'
    model_name text,
    created_at timestamptz not null default now()
);

-- 10. Request Rate Limiting / Audit Log
create table if not exists public.rate_limit_logs (
    id bigserial primary key,
    user_id uuid references public.profiles(id) on delete set null,
    endpoint text not null,
    created_at timestamptz not null default now()
);

-- 11. Hybrid 5-Tier Search RPC (preserves search tier tag while returning legal authority & effective date)
create or replace function public.search_railway_rules(
    query_embedding vector(1536),
    query_text text,
    p_zone_id uuid,
    p_division_id uuid,
    p_department_id uuid,
    match_limit int default 18
)
returns table (
    chunk_id uuid,
    document_id uuid,
    document_title text,
    document_number text,
    document_type text,
    issuing_authority text,
    authority_rank int,
    issue_date date,
    effective_date date,
    page_number int,
    rule_number text,
    section_title text,
    content text,
    search_tier int,
    search_tier_label text,
    is_superseded boolean,
    superseded_by_ref text,
    similarity_score double precision
)
language sql
stable
security definer
as $$
    with scoped_docs as (
        select
            d.id as doc_id,
            min(
                case
                    when ds.scope_level = 'DEPARTMENT'
                         and ds.zone_id = p_zone_id
                         and (ds.division_id is null or ds.division_id = p_division_id)
                         and ds.department_id = p_department_id then 1
                    when ds.scope_level in ('DEPARTMENT', 'DIVISION')
                         and ds.zone_id = p_zone_id
                         and ds.division_id = p_division_id then 2
                    when ds.scope_level = 'ZONE'
                         and ds.zone_id = p_zone_id then 3
                    when ds.scope_level = 'RAILWAY_BOARD' then 4
                    else 5
                end
            ) as tier
        from public.documents d
        join public.document_scopes ds on ds.document_id = d.id
        where d.status in ('published', 'superseded')
          and (
              (ds.scope_level = 'DEPARTMENT' and ds.zone_id = p_zone_id and ds.department_id = p_department_id)
              or (ds.scope_level in ('DEPARTMENT', 'DIVISION') and ds.zone_id = p_zone_id and ds.division_id = p_division_id)
              or (ds.scope_level = 'ZONE' and ds.zone_id = p_zone_id)
              or (ds.scope_level in ('RAILWAY_BOARD', 'COMMON'))
          )
        group by d.id
    )
    select
        rc.id as chunk_id,
        d.id as document_id,
        d.title as document_title,
        d.document_number,
        d.document_type,
        d.issuing_authority,
        d.authority_rank,
        d.issue_date,
        d.effective_date,
        rc.page_number,
        rc.rule_number,
        rc.section_title,
        rc.content,
        sd.tier as search_tier,
        case sd.tier
            when 1 then 'Selected Department'
            when 2 then 'Other Dept in Division'
            when 3 then 'Zone-Wide'
            when 4 then 'Railway Board'
            else 'Common Railway Rules'
        end as search_tier_label,
        (d.status = 'superseded' or exists (
            select 1 from public.amendments a
            where a.target_document_id = d.id and a.relationship_type in ('SUPERSEDES', 'REPEALS')
        )) as is_superseded,
        (
            select string_agg(coalesce(ad.document_number, ad.title), '; ')
            from public.amendments a
            join public.documents ad on ad.id = a.amending_document_id
            where a.target_document_id = d.id
        ) as superseded_by_ref,
        (
            0.75 * (1 - (rc.embedding <=> query_embedding)) +
            0.25 * ts_rank_cd(rc.content_tsv, plainto_tsquery('english', query_text))
        ) as similarity_score
    from public.rule_chunks rc
    join public.documents d on d.id = rc.document_id
    join scoped_docs sd on sd.doc_id = d.id
    order by similarity_score desc, d.authority_rank desc, d.effective_date desc nulls last
    limit match_limit;
$$;

-- 12. Row-Level Security (RLS)
alter table public.zones enable row level security;
alter table public.divisions enable row level security;
alter table public.departments enable row level security;
alter table public.profiles enable row level security;
alter table public.documents enable row level security;
alter table public.document_scopes enable row level security;
alter table public.rule_chunks enable row level security;
alter table public.amendments enable row level security;
alter table public.chat_sessions enable row level security;
alter table public.chat_messages enable row level security;

create policy "Anyone can read active zones" on public.zones for select using (true);
create policy "Anyone can read active divisions" on public.divisions for select using (true);
create policy "Anyone can read active departments" on public.departments for select using (true);

create policy "Users view own profile" on public.profiles for select using (auth.uid() = id);
create policy "Users update own profile" on public.profiles for update using (auth.uid() = id);

create policy "Authenticated read published docs" on public.documents
    for select to authenticated using (status in ('published', 'superseded'));

create policy "Admins manage all documents" on public.documents
    for all to authenticated using (
        exists (select 1 from public.profiles p where p.id = auth.uid() and p.role = 'admin')
    );

create policy "Users manage own chat sessions" on public.chat_sessions
    for all to authenticated using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy "Users manage own chat messages" on public.chat_messages
    for all to authenticated using (
        exists (select 1 from public.chat_sessions s where s.id = session_id and s.user_id = auth.uid())
    );

-- 13. Seed Initial Taxonomy (Western Railway Active + 6 WR Divisions + 13 Departments)
insert into public.zones (code, name, name_hi, is_active, is_national_board, sort_order) values
    ('WR', 'Western Railway', 'पश्चिम रेलवे', true, false, 1),
    ('CR', 'Central Railway', 'मध्य रेलवे', false, false, 2),
    ('NR', 'Northern Railway', 'उत्तर रेलवे', false, false, 3),
    ('SR', 'Southern Railway', 'दक्षिण रेलवे', false, false, 4),
    ('ER', 'Eastern Railway', 'पूर्व रेलवे', false, false, 5),
    ('SCR', 'South Central Railway', 'दक्षिण मध्य रेलवे', false, false, 6),
    ('SER', 'South Eastern Railway', 'दक्षिण पूर्व रेलवे', false, false, 7),
    ('NER', 'North Eastern Railway', 'पूर्वोत्तर रेलवे', false, false, 8),
    ('NFR', 'Northeast Frontier Railway', 'पूर्वोत्तर सीमा रेलवे', false, false, 9),
    ('NWR', 'North Western Railway', 'उत्तर पश्चिम रेलवे', false, false, 10),
    ('ECR', 'East Central Railway', 'पूर्व मध्य रेलवे', false, false, 11),
    ('ECoR', 'East Coast Railway', 'पूर्व तट रेलवे', false, false, 12),
    ('NCR', 'North Central Railway', 'उत्तर मध्य रेलवे', false, false, 13),
    ('SECR', 'South East Central Railway', 'दक्षिण पूर्व मध्य रेलवे', false, false, 14),
    ('SWR', 'South Western Railway', 'दक्षिण पश्चिम रेलवे', false, false, 15),
    ('WCR', 'West Central Railway', 'पश्चिम मध्य रेलवे', false, false, 16),
    ('METRO', 'Metro Railway Kolkata', 'मेट्रो रेलवे कोलकाता', false, false, 17)
on conflict (code) do nothing;

insert into public.divisions (zone_id, code, name, name_hi, is_active, sort_order)
select z.id, v.code, v.name, v.name_hi, true, v.sort_order
from public.zones z
cross join (values
    ('BCT', 'Mumbai Central', 'मुंबई सेंट्रल', 1),
    ('BRC', 'Vadodara', 'वडोदरा', 2),
    ('ADI', 'Ahmedabad', 'अहमदाबाद', 3),
    ('RTM', 'Ratlam', 'रतलाम', 4),
    ('RJT', 'Rajkot', 'राजकोट', 5),
    ('BVP', 'Bhavnagar', 'भावनगर', 6)
) as v(code, name, name_hi, sort_order)
where z.code = 'WR'
on conflict (zone_id, code) do nothing;

insert into public.departments (code, name, name_hi, is_active, sort_order) values
    ('ENG', 'Engineering', 'इंजीनियरिंग', true, 1),
    ('OPT', 'Operating', 'परिचालन', true, 2),
    ('COM', 'Commercial', 'वाणिज्य', true, 3),
    ('PER', 'Personnel', 'कार्मिक', true, 4),
    ('ELE', 'Electrical', 'विद्युत', true, 5),
    ('MEC', 'Mechanical', 'यांत्रिक', true, 6),
    ('SNT', 'Signal & Telecommunication', 'सिग्नल एवं दूरसंचार', true, 7),
    ('ACC', 'Accounts', 'लेखा', true, 8),
    ('STR', 'Stores', 'भंडार', true, 9),
    ('MED', 'Medical', 'चिकित्सा', true, 10),
    ('SAF', 'Safety', 'संरक्षा', true, 11),
    ('RPF', 'Security (RPF)', 'सुरक्षा (आरपीएफ)', true, 12),
    ('OTH', 'Other', 'अन्य', true, 13)
on conflict (code) do nothing;
