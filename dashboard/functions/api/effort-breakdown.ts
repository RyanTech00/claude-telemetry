interface Env {
  SUPABASE_URL: string;
  SUPABASE_SERVICE_KEY: string;
}

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export const onRequestGet: PagesFunction<Env> = async (context) => {
  const url = new URL(context.request.url);
  const start_date = url.searchParams.get("start_date");
  const end_date = url.searchParams.get("end_date");
  const machine_id = url.searchParams.get("machine_id");

  if (!start_date || !end_date || !DATE_RE.test(start_date) || !DATE_RE.test(end_date)) {
    return new Response(
      JSON.stringify({ error: "start_date and end_date (YYYY-MM-DD) are required" }),
      { status: 400, headers: { "Content-Type": "application/json" } },
    );
  }
  if (machine_id && !UUID_RE.test(machine_id)) {
    return new Response(
      JSON.stringify({ error: "machine_id must be a UUID" }),
      { status: 400, headers: { "Content-Type": "application/json" } },
    );
  }

  const response = await fetch(
    `${context.env.SUPABASE_URL}/rest/v1/rpc/get_effort_breakdown`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        apikey: context.env.SUPABASE_SERVICE_KEY,
        Authorization: `Bearer ${context.env.SUPABASE_SERVICE_KEY}`,
      },
      body: JSON.stringify({
        p_start_date: start_date,
        p_end_date: end_date,
        p_machine_id: machine_id || null,
      }),
    },
  );

  const data = await response.json();
  return new Response(JSON.stringify(data), {
    status: response.status,
    headers: { "Content-Type": "application/json" },
  });
};
