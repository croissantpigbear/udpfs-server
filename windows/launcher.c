/* UDPFS Server.exe / OPL Library.exe: starts the window with the Python
   that ships beside it (python\pythonw.exe app\<SCRIPT>), passing any
   arguments on. Built once per program with -DSCRIPT and -DAPPNAME. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <wchar.h>

#ifndef SCRIPT
#define SCRIPT L"udpfs_gui.pyw"
#endif
#ifndef APPNAME
#define APPNAME L"UDPFS Server"
#endif

static void dir_of(wchar_t *path)
{
    wchar_t *s = wcsrchr(path, L'\\');
    if (s)
        *s = 0;
}

int WINAPI wWinMain(HINSTANCE hi, HINSTANCE hp, LPWSTR args, int show)
{
    static wchar_t self[MAX_PATH], py[MAX_PATH], gui[MAX_PATH], cmd[4 * MAX_PATH + 2048];
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;

    (void)hi; (void)hp; (void)show;
    GetModuleFileNameW(NULL, self, MAX_PATH);
    dir_of(self);
    _snwprintf(py, MAX_PATH, L"%ls\\python\\pythonw.exe", self);
    _snwprintf(gui, MAX_PATH, L"%ls\\app\\%ls", self, SCRIPT);

    if (GetFileAttributesW(py) == INVALID_FILE_ATTRIBUTES || GetFileAttributesW(gui) == INVALID_FILE_ATTRIBUTES) {
        MessageBoxW(NULL, L"The python and app folders must stay next to this program.\n\n"
                          L"Extract the whole zip, then run it from that folder.",
                    APPNAME, MB_ICONERROR);
        return 1;
    }

    _snwprintf(cmd, sizeof(cmd) / sizeof(cmd[0]), L"\"%ls\" \"%ls\" %ls", py, gui, args ? args : L"");
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    if (!CreateProcessW(py, cmd, NULL, NULL, FALSE, 0, NULL, self, &si, &pi)) {
        MessageBoxW(NULL, L"Could not start the bundled Python.", APPNAME, MB_ICONERROR);
        return 1;
    }
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 0;
}
