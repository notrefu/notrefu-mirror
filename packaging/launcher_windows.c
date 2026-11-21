/* notrefu-mirror.exe : petit lanceur. Il règle l'environnement puis démarre python\pythonw.exe -m notrefu_mirror, sans console. */
#include <windows.h>
#include <wchar.h>

int WINAPI WinMain(HINSTANCE inst, HINSTANCE prev, LPSTR cmd, int show) {
    wchar_t dir[MAX_PATH * 2], tmp[MAX_PATH * 4], line[MAX_PATH * 4];
    (void)inst; (void)prev; (void)cmd; (void)show;
    DWORD n = GetModuleFileNameW(NULL, dir, MAX_PATH * 2);
    if (n == 0 || n >= MAX_PATH * 2) return 1;
    wchar_t *slash = wcsrchr(dir, L'\\');
    if (!slash) return 1;
    slash[1] = 0; /* dir = « C:\...\notrefu-mirror\ » */
    SetEnvironmentVariableW(L"NOTREFU_MIRROR_HOME", dir);
    swprintf(tmp, MAX_PATH * 4, L"%lsapp", dir);
    SetEnvironmentVariableW(L"PYTHONPATH", tmp);
    SetEnvironmentVariableW(L"PYTHONNOUSERSITE", L"1");
    SetEnvironmentVariableW(L"PYTHONDONTWRITEBYTECODE", L"1");
    swprintf(tmp, MAX_PATH * 4, L"%lspython\\pythonw.exe", dir);
    swprintf(line, MAX_PATH * 4, L"\"%ls\" -m notrefu_mirror", tmp);
    STARTUPINFOW si = {0};
    si.cb = sizeof(si);
    PROCESS_INFORMATION pi = {0};
    if (!CreateProcessW(tmp, line, NULL, NULL, FALSE, 0, NULL, dir, &si, &pi)) {
        MessageBoxW(NULL, L"Impossible de démarrer notrefu-mirror : le dossier « python » est introuvable.\nDézippe tout le dossier avant de lancer notrefu-mirror.exe.", L"notrefu-mirror", MB_ICONERROR);
        return 1;
    }
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 0;
}
