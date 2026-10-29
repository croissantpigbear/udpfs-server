/* UDPFS Server.exe: starts the window with the Python that ships beside it
   (python\pythonw.exe app\udpfs_gui.pyw), passing any arguments on. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <wchar.h>

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
    _snwprintf(gui, MAX_PATH, L"%ls\\app\\udpfs_gui.pyw", self);

    if (GetFileAttributesW(py) == INVALID_FILE_ATTRIBUTES || GetFileAttributesW(gui) == INVALID_FILE_ATTRIBUTES) {
        MessageBoxW(NULL, L"The python and app folders must stay next to UDPFS Server.exe.\n\n"
                          L"Extract the whole zip, then run UDPFS Server.exe from that folder.",
                    L"UDPFS Server", MB_ICONERROR);
        return 1;
    }

    _snwprintf(cmd, sizeof(cmd) / sizeof(cmd[0]), L"\"%ls\" \"%ls\" %ls", py, gui, args ? args : L"");
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    if (!CreateProcessW(py, cmd, NULL, NULL, FALSE, 0, NULL, self, &si, &pi)) {
        MessageBoxW(NULL, L"Could not start the bundled Python.", L"UDPFS Server", MB_ICONERROR);
        return 1;
    }
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 0;
}
