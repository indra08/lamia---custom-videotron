// Pages serves static assets; the existing Worker retains API, sessions, D1/KV and Cron.
export const appPaths = ['/admin','/schedule','/login','/player','/static/player.html','/terms','/privacy','/status'];
export default {
  async fetch(request,env) {
    const path = new URL(request.url).pathname;
    if (path === '/api' || path.startsWith('/api/') || appPaths.includes(path)) {
      if (!env.APP) return Response.json({detail:'Backend belum terhubung'},{status:503,headers:{'Cache-Control':'no-store'}});
      // Preserve the Pages URL and Origin for CSRF and host-scoped admin cookies.
      return env.APP.fetch(request);
    }
    return env.ASSETS.fetch(request);
  }
};
