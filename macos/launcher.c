/*
  UDPFS Server.app / OPL Library.app launcher (macOS).

  Runs the bundled Python inside this process (libpython is loaded with
  dlopen), so macOS sees the app itself, signed and with its bundle id,
  as the program using the network. Local Network permission then has an
  app to ask about and to list under Privacy & Security, and the server
  Python starts as a child inherits it. A shell script that exec'd Python
  left macOS with nothing to attribute it to.

  Built as one universal binary: the arm64 half loads python-aarch64,
  the x86_64 half (Intel Macs, or Rosetta) loads python-x86_64.

  SCRIPT     the .pyw to run, in Contents/Resources/app
  FIND_SERVER  look for the Python in UDPFS Server.app next to this app
               (OPL Library carries no Python of its own)
*/
#include <dlfcn.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#ifndef SCRIPT
#define SCRIPT "udpfs_gui.pyw"
#endif

#if defined(__aarch64__) || defined(__arm64__)
#define PYARCH "aarch64"
#else
#define PYARCH "x86_64"
#endif

static void alert(const char *title, const char *msg)
{
    char cmd[1024];
    snprintf(cmd, sizeof(cmd), "/usr/bin/osascript -e 'display alert \"%s\" message \"%s\" as critical'", title, msg);
    system(cmd);
}

static int is_file(const char *p)
{
    struct stat st;
    return stat(p, &st) == 0 && S_ISREG(st.st_mode);
}

/* Resources folder that holds python-ARCH and app/SCRIPT, or 0. */
static int find_resources(const char *bundle, char *res, size_t size)
{
    char p[PATH_MAX * 2];
    snprintf(res, size, "%s/Contents/Resources", bundle);
    snprintf(p, sizeof(p), "%s/app/" SCRIPT, res);
    if (!is_file(p))
        return 0;
    snprintf(p, sizeof(p), "%s/python-" PYARCH "/lib/libpython3.12.dylib", res);
    return is_file(p);
}

int main(int argc, char **argv)
{
    char exe[PATH_MAX], real[PATH_MAX], bundle[PATH_MAX], res[PATH_MAX * 2];
    uint32_t n = sizeof(exe);

    if (_NSGetExecutablePath(exe, &n) != 0 || !realpath(exe, real)) {
        alert("Could not start", "The app could not find itself.");
        return 1;
    }
    /* real = .../X.app/Contents/MacOS/X */
    strcpy(bundle, real);
    for (int i = 0; i < 3; i++) {
        char *s = strrchr(bundle, '/');
        if (s)
            *s = 0;
    }

    int found = 0;
#ifdef FIND_SERVER
    {
        char parent[PATH_MAX], cand[PATH_MAX * 2];
        const char *home = getenv("HOME");
        strcpy(parent, bundle);
        char *s = strrchr(parent, '/');
        if (s)
            *s = 0;
        const char *dirs[3] = {parent, "/Applications", NULL};
        char homeapps[PATH_MAX];
        if (home) {
            snprintf(homeapps, sizeof(homeapps), "%s/Applications", home);
            dirs[2] = homeapps;
        }
        for (int i = 0; i < 3 && !found; i++) {
            if (!dirs[i])
                continue;
            snprintf(cand, sizeof(cand), "%s/UDPFS Server.app", dirs[i]);
            found = find_resources(cand, res, sizeof(res));
        }
        if (!found) {
            alert("OPL Library needs UDPFS Server",
                  "Put OPL Library and UDPFS Server in the same folder (for example Applications), then open OPL Library again.");
            return 1;
        }
    }
#else
    found = find_resources(bundle, res, sizeof(res));
    if (!found) {
        alert("UDPFS Server is damaged", "Download it again and copy the whole app.");
        return 1;
    }
#endif

    char home[PATH_MAX * 2], py[PATH_MAX * 3], lib[PATH_MAX * 3], script[PATH_MAX * 3];
    snprintf(home, sizeof(home), "%s/python-" PYARCH, res);
    snprintf(py, sizeof(py), "%s/bin/python3", home);
    snprintf(lib, sizeof(lib), "%s/lib/libpython3.12.dylib", home);
    snprintf(script, sizeof(script), "%s/app/" SCRIPT, res);

    /* The Python's own home, and sys.executable = its python3, so the
       server and OPL Library start as ordinary child Pythons. */
    setenv("PYTHONHOME", home, 1);
    setenv("PYTHONEXECUTABLE", py, 1);
    unsetenv("PYTHONPATH");
#ifndef FIND_SERVER
    /* For "Open at login": start this app, not a bare Python. */
    setenv("UDPFS_APP_LAUNCHER", real, 1);
#endif
    /* Keep compiled files out of the signed app. */
    const char *uh = getenv("HOME");
    if (uh) {
        char cache[PATH_MAX];
        snprintf(cache, sizeof(cache), "%s/Library/Caches/UDPFS Server/pycache", uh);
        setenv("PYTHONPYCACHEPREFIX", cache, 1);
    } else
        setenv("PYTHONDONTWRITEBYTECODE", "1", 1);

    void *h = dlopen(lib, RTLD_NOW | RTLD_GLOBAL);
    if (!h) {
        alert("Could not start", "The Python inside the app could not be loaded. Download it again and copy the whole app.");
        fprintf(stderr, "%s\n", dlerror());
        return 1;
    }
    int (*bytes_main)(int, char **) = (int (*)(int, char **))dlsym(h, "Py_BytesMain");
    if (!bytes_main) {
        alert("Could not start", "The Python inside the app is incomplete.");
        return 1;
    }

    /* python3 SCRIPT args... (Finder may add -psn_...; drop it) */
    char **av = calloc(argc + 3, sizeof(char *));
    int ac = 0;
    av[ac++] = py;
    av[ac++] = script;
    for (int i = 1; i < argc; i++)
        if (strncmp(argv[i], "-psn_", 5) != 0)
            av[ac++] = argv[i];
    av[ac] = NULL;
    return bytes_main(ac, av);
}
