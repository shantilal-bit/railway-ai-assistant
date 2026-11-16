-- ============================================================================
-- 003_short_query_and_hybrid_search.sql
-- Non-destructive search upgrade for short queries, Hinglish/Hindi FTS OR matching,
-- bidirectional rule number matching (4.10 <-> GR 4.10 / SR 4.10.1), adaptive
-- hybrid scoring, and NULL query_embedding FTS fallback.
-- Preserves all existing tables, 1309 rule_chunks, 1024-dim embedding_bge_m3,
-- document_scopes, authority_rank, amendments, and RLS policies.
-- ============================================================================

create or replace function public.build_railway_or_tsquery(
    cfg regconfig,
    raw_text text
)
returns tsquery
language plpgsql
immutable
as $$
declare
    v_tok text;
    v_part tsquery;
    v_acc tsquery := null;
    v_count int := 0;
begin
    if raw_text is null or trim(raw_text) = '' then
        return null;
    end if;

    for v_tok in
        select distinct trim(both '.,?;:()[]{}''"' from m)
        from regexp_split_to_table(trim(raw_text), '\s+') as m
        where length(trim(both '.,?;:()[]{}''"' from m)) >= 2
    loop
        v_part := plainto_tsquery(cfg, v_tok);
        if v_part is not null and v_part <> ''::tsquery then
            v_acc := case when v_acc is null then v_part else (v_acc || v_part) end;
            v_count := v_count + 1;
        end if;
        exit when v_count >= 14;
    end loop;

    return v_acc;
end;
$$;

create or replace function public.search_railway_rules(
    query_embedding vector(1024),
    query_text text,
    p_zone_id text,
    p_division_id text,
    p_department_id text,
    match_limit int default 18
)
returns table (
    chunk_id text,
    document_id text,
    document_title text,
    document_number text,
    document_type text,
    issuing_authority text,
    authority_rank int,
    issue_date date,
    effective_date date,
    page_number int,
    rule_number text,
    chapter text,
    section_title text,
    content text,
    search_tier int,
    search_tier_label text,
    is_superseded boolean,
    superseded_by_ref text,
    vector_score double precision,
    keyword_score double precision,
    similarity_score double precision
)
language sql
stable
security definer
set search_path = public, extensions
as $$
    with cleaned_query as (
        select
            nullif(trim(coalesce(query_text, '')), '') as q_raw,
            plainto_tsquery('english', coalesce(query_text, '')) as q_eng_and,
            plainto_tsquery('simple', coalesce(query_text, '')) as q_simple_and,
            public.build_railway_or_tsquery('english'::regconfig, query_text) as q_eng_or,
            public.build_railway_or_tsquery('simple'::regconfig, query_text) as q_simple_or,
            array(
                select distinct lower(m[1])
                from regexp_matches(
                    coalesce(query_text, ''),
                    '([0-9]{1,3}\.[0-9]{1,3}(?:\.[0-9]{1,3})*|[0-9]{1,4}/[0-9]{2,4})',
                    'g'
                ) as m
            ) as rule_num_tokens
    ),
    scoped_docs as (
        select
            d.id as doc_id,
            min(
                case
                    when ds.scope_level = 'DEPARTMENT'
                         and ds.zone_id::text = p_zone_id
                         and ds.division_id::text = p_division_id
                         and ds.department_id::text = p_department_id then 1
                    when ds.scope_level = 'DEPARTMENT'
                         and ds.zone_id::text = p_zone_id
                         and ds.division_id is null
                         and ds.department_id::text = p_department_id then 2
                    when ds.scope_level in ('DEPARTMENT', 'DIVISION')
                         and ds.zone_id::text = p_zone_id
                         and ds.division_id::text = p_division_id then 3
                    when ds.scope_level = 'ZONE'
                         and ds.zone_id::text = p_zone_id then 4
                    else 5
                end
            ) as tier
        from public.documents d
        join public.document_scopes ds on ds.document_id = d.id
        where coalesce(d.status, 'published') in ('published', 'superseded', 'active')
          and d.ingestion_status = 'completed'
          and (
              (ds.scope_level = 'DEPARTMENT'
               and ds.zone_id::text = p_zone_id
               and ds.department_id::text = p_department_id
               and (ds.division_id is null or ds.division_id::text = p_division_id))
              or (ds.scope_level in ('DEPARTMENT', 'DIVISION')
                  and ds.zone_id::text = p_zone_id
                  and ds.division_id::text = p_division_id)
              or (ds.scope_level = 'ZONE'
                  and ds.zone_id::text = p_zone_id)
              or (ds.scope_level in ('RAILWAY_BOARD', 'COMMON')
                  and (ds.zone_id is null or ds.zone_id::text = p_zone_id))
          )
        group by d.id
    ),
    scored as (
        select
            rc.id::text as chunk_id,
            d.id::text as document_id,
            d.title as document_title,
            d.document_number,
            d.document_type,
            d.issuing_authority,
            d.authority_rank,
            d.issue_date,
            d.effective_date,
            rc.page_number,
            rc.rule_number,
            rc.chapter,
            rc.section_title,
            rc.content,
            sd.tier as search_tier,
            case sd.tier
                when 1 then 'Selected Dept + Division + Zone'
                when 2 then 'Selected Dept + Zone'
                when 3 then 'Selected Division (Other Dept)'
                when 4 then 'Zone-Wide'
                else 'Railway Board / Common'
            end as search_tier_label,
            (
                d.status = 'superseded'
                or exists (
                    select 1
                    from public.amendments a
                    where a.target_document_id = d.id
                      and upper(coalesce(a.relationship_type, '')) in ('SUPERSEDES', 'REPEALS')
                )
            ) as is_superseded,
            (
                select string_agg(coalesce(ad.document_number, ad.title, a.circular_reference), '; ')
                from public.amendments a
                left join public.documents ad on ad.id = a.amending_document_id
                where a.target_document_id = d.id
            ) as superseded_by_ref,
            case
                when query_embedding is null or rc.embedding_bge_m3 is null then 0.0::double precision
                else greatest(0.0, 1.0 - (rc.embedding_bge_m3 <=> query_embedding))::double precision
            end as vector_score,
            (
                case
                    when cq.q_raw is null then 0.0
                    else (
                        -- Phrase / AND precision signal
                        coalesce(ts_rank_cd(rc.search_tsv, cq.q_simple_and), 0.0) * 0.35
                        + coalesce(ts_rank_cd(rc.search_tsv, cq.q_eng_and), 0.0) * 0.25
                        -- Flexible OR signal for short, colloquial, and expanded bilingual queries
                        + case
                            when cq.q_simple_or is not null then coalesce(ts_rank_cd(rc.search_tsv, cq.q_simple_or), 0.0) * 0.35
                            else 0.0
                          end
                        + case
                            when cq.q_eng_or is not null then coalesce(ts_rank_cd(rc.search_tsv, cq.q_eng_or), 0.0) * 0.25
                            else 0.0
                          end
                        -- Boundary-aware bidirectional rule_number match (e.g. "4.10" <-> "GR 4.10" / "SR 4.10.1", never "4.1" -> "4.10")
                        + case
                            when nullif(trim(coalesce(rc.rule_number, '')), '') is not null
                                 and (
                                     (
                                         ' ' || regexp_replace(lower(cq.q_raw), '[^0-9a-z./-]+', ' ', 'g') || ' '
                                     ) like (
                                         '% ' || regexp_replace(lower(trim(rc.rule_number)), '[^0-9a-z./-]+', ' ', 'g') || ' %'
                                     )
                                     or exists (
                                         select 1
                                         from unnest(cq.rule_num_tokens) as rt(tok)
                                         where lower(trim(rc.rule_number)) ~ (
                                             '(?:^|[^0-9.])' || replace(rt.tok, '.', '\.') || '(?:$|[^0-9.])'
                                         )
                                     )
                                 )
                            then 0.70
                            else 0.0
                          end
                        + case
                            when nullif(trim(coalesce(d.document_number, '')), '') is not null
                                 and (
                                     ' ' || regexp_replace(lower(cq.q_raw), '[^0-9a-z./-]+', ' ', 'g') || ' '
                                 ) like (
                                     '% ' || regexp_replace(lower(trim(d.document_number)), '[^0-9a-z./-]+', ' ', 'g') || ' %'
                                 )
                            then 0.55
                            else 0.0
                          end
                    )
                end
            )::double precision as keyword_score
        from public.rule_chunks rc
        join public.documents d on d.id = rc.document_id
        join scoped_docs sd on sd.doc_id = d.id
        cross join cleaned_query cq
        where (
            (query_embedding is not null and rc.embedding_bge_m3 is not null)
            or (
                query_embedding is null
                and cq.q_raw is not null
                and (
                    (cq.q_simple_or is not null and rc.search_tsv @@ cq.q_simple_or)
                    or (cq.q_eng_or is not null and rc.search_tsv @@ cq.q_eng_or)
                    or exists (
                        select 1
                        from unnest(cq.rule_num_tokens) as rt(tok)
                        where lower(coalesce(rc.rule_number, '')) ~ (
                            '(?:^|[^0-9.])' || replace(rt.tok, '.', '\.') || '(?:$|[^0-9.])'
                        )
                    )
                )
            )
        )
    )
    select
        s.chunk_id,
        s.document_id,
        s.document_title,
        s.document_number,
        s.document_type,
        s.issuing_authority,
        s.authority_rank,
        s.issue_date,
        s.effective_date,
        s.page_number,
        s.rule_number,
        s.chapter,
        s.section_title,
        s.content,
        s.search_tier,
        s.search_tier_label,
        s.is_superseded,
        s.superseded_by_ref,
        s.vector_score,
        s.keyword_score,
        (
            case
                when query_embedding is null then least(1.0, s.keyword_score)
                else greatest(
                    0.92 * s.vector_score + 0.08 * least(1.0, s.keyword_score),
                    0.68 * s.vector_score + 0.32 * least(1.0, s.keyword_score)
                )
            end
        )::double precision as similarity_score
    from scored s
    order by
        similarity_score desc,
        s.is_superseded asc,
        s.authority_rank desc,
        s.effective_date desc nulls last,
        s.search_tier asc
    limit greatest(1, least(coalesce(match_limit, 18), 50));
$$;

revoke all on function public.build_railway_or_tsquery(regconfig, text) from public;
grant execute on function public.build_railway_or_tsquery(regconfig, text) to authenticated, service_role;

revoke all on function public.search_railway_rules(vector(1024), text, text, text, text, int) from public;
revoke all on function public.search_railway_rules(vector(1024), text, text, text, text, int) from anon;
grant execute on function public.search_railway_rules(vector(1024), text, text, text, text, int) to authenticated, service_role;
