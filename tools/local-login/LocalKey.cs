// Private-server test launcher: same key-store validation as app/src-tauri/src/patcher/mod.rs.
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;

namespace ForeverLocalLogin
{
    public interface IMemory
    {
        byte[] Read(ulong address, int length);
        bool Write(ulong address, byte[] bytes);
    }

    public static class KeyStore
    {
        public const int Size = 480;
        public const int TargetOffset = 284; // (region group 8 - 1) * 40 + 4
        static readonly string[] Keys = {
            "9B0671C815DFF513BFD4A2B26AE1F84EC9106841B2FB620DB65F6ADE7C21AD06",
            "112451B9843C2799E4750AA3D9B9AFABF536A645B863C4ADB2078B932B354E04",
            "A6B858485748BF38BE193517AB90F8DE169EFF0989EA9360DB346A378B0FFE15",
            "50FFDEB807F8FF73A299A16000AA6575C5945BE875ADFC8795374ED3415249AC",
            "9F842D078755647C008E5FE3E12B839A981DE02A1F520CB2545CC04CD2323E0E",
            "B8CC75864D8EF461D8DD6AA7425E2C63C24D3982066B8D773A1549BFE24E05EE",
            "76BB7BBDD9F34E124A4573C3AA227E3C87CC603506697D054F6FDEC342E56EBF",
            "1FD6DD8FA0EC30D39E3F72E755B8A045BDE0F70449DC71008B767C2EAA89FB9F",
            "15D618BD7DB577BD9A8D45769C59E4FC631633BF447398A4B489B4C26FBC03AD",
            "B34EC592D2AC4993F5FFC85B15C3DA9078694051CB224345592AF7136D796C99",
            "9E91586DD4B115AB0568B21959E181F6545910BC5E2F30B8975CA09D7BC3EFCE",
            "769C824A1DADD19AEEFA420414D1732DAF44537F98AA229FC5477BCA55F9D59A"
        };
        static readonly byte[][] Original = Array.ConvertAll(Keys, Hex);
        static readonly int[] Skip = MakeSkip();

        public static byte[] Hex(string text)
        {
            if (text == null || text.Length != 64) throw new ArgumentException("Expected a 32-byte public key");
            var bytes = new byte[32];
            for (int i = 0; i < bytes.Length; ++i) bytes[i] = Convert.ToByte(text.Substring(i * 2, 2), 16);
            return bytes;
        }

        static int[] MakeSkip()
        {
            var table = new int[256];
            for (int i = 0; i < table.Length; ++i) table[i] = 32;
            for (int i = 0; i < 31; ++i) table[Original[0][i]] = 31 - i;
            return table;
        }

        static bool Equal(byte[] data, int offset, byte[] wanted)
        {
            for (int i = 0; i < wanted.Length; ++i) if (data[offset + i] != wanted[i]) return false;
            return true;
        }

        // 0: invalid; 1: original; 2: already configured for this server.
        public static int State(byte[] data, int start, byte[] replacement)
        {
            if (data == null || start < 0 || start > data.Length - Size || replacement.Length != 32) return 0;
            for (int entry = 0; entry < 12; ++entry)
            {
                int offset = start + entry * 40;
                if (BitConverter.ToUInt32(data, offset) != (uint)(entry + 1)) return 0;
                bool matches = Equal(data, offset + 4, Original[entry]);
                if (entry == 7) matches = matches || Equal(data, offset + 4, replacement);
                if (!matches || data[offset + 36] != (entry == 8 ? 0 : 1) ||
                    data[offset + 38] != 0 || data[offset + 39] != 0) return 0;
                // offset+37 is uninitialized padding, as in the existing Rust launcher.
            }
            return Equal(data, start + TargetOffset, replacement) ? 2 : 1;
        }

        public static List<ulong> Find(byte[] data, ulong baseAddress, byte[] replacement)
        {
            var result = new List<ulong>();
            if (data == null) return result;
            for (int i = 0; i <= data.Length - 32; )
            {
                if (data[i + 31] == Original[0][31] && Equal(data, i, Original[0]))
                {
                    if (i >= 4 && (baseAddress + (ulong)i - 4) % 4 == 0 && State(data, i - 4, replacement) != 0)
                        result.Add(baseAddress + (ulong)i - 4);
                    ++i;
                }
                else i += Skip[data[i + 31]];
            }
            return result;
        }

        public static bool PatchUnique(IMemory memory, IList<ulong> candidates, byte[] replacement)
        {
            if (candidates.Count != 1) return false;
            ulong address = candidates[0];
            int state = State(memory.Read(address, Size), 0, replacement);
            if (state == 0) return false;
            if (state == 2) return true;
            if (!memory.Write(address + TargetOffset, replacement)) throw new IOException("Public-key write failed");
            if (State(memory.Read(address, Size), 0, replacement) != 2)
                throw new IOException("Public-key readback verification failed");
            return true;
        }
    }

    public sealed class Session : IMemory, IDisposable
    {
        [StructLayout(LayoutKind.Sequential)]
        struct Region
        {
            public IntPtr BaseAddress, AllocationBase;
            public uint AllocationProtect;
            public UIntPtr RegionSize;
            public uint State, Protect, Type;
        }
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern IntPtr OpenProcess(uint access, bool inherit, int processId);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool CloseHandle(IntPtr handle);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool ReadProcessMemory(IntPtr process, IntPtr address, [Out] byte[] data, UIntPtr length, out UIntPtr read);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool WriteProcessMemory(IntPtr process, IntPtr address, byte[] data, UIntPtr length, out UIntPtr written);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern UIntPtr VirtualQueryEx(IntPtr process, IntPtr address, out Region info, UIntPtr size);
        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool GetExitCodeProcess(IntPtr process, out uint code);

        IntPtr handle;
        readonly byte[] replacement;
        ulong current;
        public int ProcessId { get; private set; }

        public Session(int processId, string expectedExe, string publicKey)
        {
            if (IntPtr.Size != 8) throw new InvalidOperationException("Use 64-bit Windows PowerShell");
            replacement = KeyStore.Hex(publicKey);
            ProcessId = processId;
            using (var process = Process.GetProcessById(processId))
                if (!String.Equals(Path.GetFullPath(process.MainModule.FileName), Path.GetFullPath(expectedExe), StringComparison.OrdinalIgnoreCase))
                    throw new InvalidOperationException("Game process path does not match the selected test copy");
            handle = OpenProcess(0x0400 | 0x0008 | 0x0010 | 0x0020, false, processId);
            if (handle == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error());
        }

        public byte[] Read(ulong address, int length)
        {
            var bytes = new byte[length];
            UIntPtr read;
            return ReadProcessMemory(handle, new IntPtr((long)address), bytes, (UIntPtr)(uint)length, out read) &&
                   read.ToUInt64() == (ulong)length ? bytes : null;
        }

        public bool Write(ulong address, byte[] bytes)
        {
            // This helper has exactly one allowed write: the 32-byte group-8 public key.
            if (current == 0 || address != current + KeyStore.TargetOffset || bytes.Length != 32)
                throw new InvalidOperationException("Write outside the validated public-key slot refused");
            UIntPtr written;
            return WriteProcessMemory(handle, new IntPtr((long)address), bytes, (UIntPtr)32, out written) && written.ToUInt64() == 32;
        }

        List<ulong> FindStores()
        {
            const int chunk = 8 * 1024 * 1024;
            var found = new SortedSet<ulong>();
            ulong cursor = 0;
            Region info;
            while (VirtualQueryEx(handle, new IntPtr((long)cursor), out info, (UIntPtr)(uint)Marshal.SizeOf(typeof(Region))) != UIntPtr.Zero)
            {
                ulong start = (ulong)info.BaseAddress.ToInt64();
                ulong size = info.RegionSize.ToUInt64();
                if (size == 0 || size > (ulong)Int64.MaxValue || start > (ulong)Int64.MaxValue - size) break;
                ulong end = start + size;
                if (info.State == 0x1000 && info.Type == 0x20000 && info.Protect == 0x04)
                {
                    for (ulong offset = start; offset < end; )
                    {
                        int take = (int)Math.Min((ulong)chunk, end - offset);
                        byte[] bytes = Read(offset, take);
                        if (bytes != null) foreach (ulong hit in KeyStore.Find(bytes, offset, replacement)) found.Add(hit);
                        if (take < chunk) break;
                        offset += (ulong)(chunk - KeyStore.Size + 1);
                    }
                }
                if (end <= cursor) break;
                cursor = end;
            }
            return new List<ulong>(found);
        }

        // -1: game exited; 0: waiting; 1: key ready. Ambiguity always stops before writing.
        public int Step()
        {
            uint exitCode;
            if (!GetExitCodeProcess(handle, out exitCode) || exitCode != 259) return -1;
            if (current != 0 && KeyStore.State(Read(current, KeyStore.Size), 0, replacement) != 0)
            {
                return KeyStore.PatchUnique(this, new ulong[] { current }, replacement) ? 1 : 0;
            }
            current = 0;
            var candidates = FindStores();
            if (candidates.Count > 1) throw new InvalidOperationException("Multiple valid key stores found; no write made");
            if (candidates.Count == 0) return 0;
            current = candidates[0];
            return KeyStore.PatchUnique(this, candidates, replacement) ? 1 : 0;
        }

        public void Dispose()
        {
            if (handle != IntPtr.Zero) CloseHandle(handle);
            handle = IntPtr.Zero;
        }
    }
}
