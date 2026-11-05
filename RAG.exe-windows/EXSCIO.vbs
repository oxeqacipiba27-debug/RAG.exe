Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
strDir = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = strDir

strPyw = strDir & "\venv\Scripts\pythonw.exe"
If Not fso.FileExists(strPyw) Then
    strPyw = strDir & "\.venv\Scripts\pythonw.exe"
End If
If Not fso.FileExists(strPyw) Then
    strPyw = strDir & "\..\venv\Scripts\pythonw.exe"
End If
If Not fso.FileExists(strPyw) Then
    strPyw = "pythonw.exe"
End If

WshShell.Run """" & strPyw & """ """ & strDir & "\run_app.py""", 0, False
