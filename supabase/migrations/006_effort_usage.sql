-- 006_effort_usage.sql
-- Daily token usage per reasoning effort level (source: agent reads Claude Code
-- transcripts directly; ccusage does not expose the effort level).

CREATE TABLE effort_usage (
    id BIGSERIAL PRIMARY KEY,
    machine_id UUID NOT NULL REFERENCES machines(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    project TEXT NOT NULL,
    model TEXT NOT NULL,
    effort TEXT NOT NULL,           -- low | medium | high | xhigh | max | unknown
    messages INTEGER DEFAULT 0,
    input_tokens BIGINT DEFAULT 0,
    output_tokens BIGINT DEFAULT 0,
    cache_creation_tokens BIGINT DEFAULT 0,
    cache_read_tokens BIGINT DEFAULT 0,
    total_tokens BIGINT DEFAULT 0,
    UNIQUE(machine_id, date, project, model, effort)
);

CREATE INDEX idx_effort_usage_machine_date ON effort_usage(machine_id, date);
CREATE INDEX idx_effort_usage_date ON effort_usage(date);

ALTER TABLE effort_usage ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users see own effort_usage" ON effort_usage FOR SELECT
    USING (machine_id IN (SELECT machine_id FROM machine_owners WHERE user_id = auth.uid()));

-- Aggregated breakdown per machine x model x effort for a date range.
CREATE OR REPLACE FUNCTION get_effort_breakdown(
    p_start_date DATE, p_end_date DATE, p_machine_id UUID DEFAULT NULL
) RETURNS TABLE(
    machine_id UUID, model TEXT, effort TEXT, messages BIGINT,
    input_tokens BIGINT, output_tokens BIGINT,
    cache_creation_tokens BIGINT, cache_read_tokens BIGINT, total_tokens BIGINT
) AS $$
BEGIN
    RETURN QUERY SELECT e.machine_id, e.model, e.effort,
        SUM(e.messages)::BIGINT,
        SUM(e.input_tokens)::BIGINT, SUM(e.output_tokens)::BIGINT,
        SUM(e.cache_creation_tokens)::BIGINT, SUM(e.cache_read_tokens)::BIGINT,
        SUM(e.total_tokens)::BIGINT
    FROM effort_usage e
    WHERE e.date BETWEEN p_start_date AND p_end_date
        AND (p_machine_id IS NULL OR e.machine_id = p_machine_id)
    GROUP BY e.machine_id, e.model, e.effort
    ORDER BY SUM(e.total_tokens) DESC;
END; $$ LANGUAGE plpgsql SECURITY DEFINER;
