using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using ForeverLocalLogin;

public class LocalKeyTests
{
    static int checks;
    static readonly byte[] Replacement = KeyStore.Hex("02596F0D0C061A8B30745988FD72C59E29EC367FB0F341F28E0F08D037BAFC69");
    static void Check(bool ok, string message) { ++checks; if (!ok) throw new Exception(message); }
    static byte[] Store()
    {
        string[] keys = (string[])typeof(KeyStore).GetField("Keys", BindingFlags.NonPublic | BindingFlags.Static).GetValue(null);
        byte[] data = new byte[KeyStore.Size];
        for (int entry = 0; entry < 12; ++entry)
        {
            Array.Copy(BitConverter.GetBytes((uint)(entry + 1)), 0, data, entry * 40, 4);
            Array.Copy(KeyStore.Hex(keys[entry]), 0, data, entry * 40 + 4, 32);
            data[entry * 40 + 36] = (byte)(entry == 8 ? 0 : 1);
            data[entry * 40 + 37] = 0x7f;
        }
        return data;
    }
    sealed class FakeMemory : IMemory
    {
        public const ulong Address = 0x10000;
        public byte[] Data = Store();
        public int Writes;
        public bool IgnoreWrite;
        public byte[] Read(ulong address, int length)
        {
            if (address != Address || length != KeyStore.Size) throw new Exception("Unexpected read");
            return (byte[])Data.Clone();
        }
        public bool Write(ulong address, byte[] bytes)
        {
            Check(address == Address + KeyStore.TargetOffset && bytes.Length == 32, "Wrong write range");
            ++Writes;
            if (!IgnoreWrite) Array.Copy(bytes, 0, Data, KeyStore.TargetOffset, 32);
            return true;
        }
    }
    public static void Main()
    {
        byte[] original = Store();
        Check(KeyStore.State(original, 0, Replacement) == 1, "Original store not recognized");
        for (int entry = 0; entry < 12; ++entry)
        {
            byte[] changed = (byte[])original.Clone(); changed[entry * 40] = 99;
            Check(KeyStore.State(changed, 0, Replacement) == 0, "Wrong group ID accepted");
            changed = (byte[])original.Clone(); changed[entry * 40 + 36] ^= 1;
            Check(KeyStore.State(changed, 0, Replacement) == 0, "Wrong flag accepted");
            changed = (byte[])original.Clone(); changed[entry * 40 + 39] = 1;
            Check(KeyStore.State(changed, 0, Replacement) == 0, "Invalid padding accepted");
            changed = (byte[])original.Clone(); changed[entry * 40 + 4] ^= 0xff;
            Check(KeyStore.State(changed, 0, Replacement) == 0, "Unexpected key accepted");
        }
        Check(KeyStore.State(new byte[32], 0, Replacement) == 0, "Short store accepted");
        Check(KeyStore.State(null, 0, Replacement) == 0, "Unreadable memory accepted");
        byte[] chunk = new byte[2048]; Array.Copy(original, 0, chunk, 128, original.Length);
        List<ulong> hits = KeyStore.Find(chunk, 0x2000, Replacement);
        Check(hits.Count == 1 && hits[0] == 0x2080, "Full store not found at the expected address");
        Check(KeyStore.Find(chunk, 0x2001, Replacement).Count == 0, "Unaligned store accepted");
        byte[] boundary = new byte[480]; Array.Copy(original, boundary, 480);
        Check(KeyStore.Find(boundary, 0x2000, Replacement).Count == 1, "Exact-size store not found");
        byte[] partial = new byte[479]; Array.Copy(original, partial, 479);
        Check(KeyStore.Find(partial, 0x2000, Replacement).Count == 0, "Partial store accepted");
        FakeMemory memory = new FakeMemory();
        Check(!KeyStore.PatchUnique(memory, new ulong[0], Replacement) && memory.Writes == 0, "Missing store caused a write");
        Check(!KeyStore.PatchUnique(memory, new ulong[] { FakeMemory.Address, FakeMemory.Address + 0x1000 }, Replacement) && memory.Writes == 0,
              "Ambiguous stores caused a write");
        memory.Data[0] = 99;
        Check(!KeyStore.PatchUnique(memory, new ulong[] { FakeMemory.Address }, Replacement) && memory.Writes == 0,
              "Store changed after discovery but was still written");
        memory = new FakeMemory();
        Check(KeyStore.PatchUnique(memory, new ulong[] { FakeMemory.Address }, Replacement), "Valid key replacement failed");
        Check(memory.Writes == 1 && KeyStore.State(memory.Data, 0, Replacement) == 2, "Write not verified");
        for (int i = 0; i < KeyStore.Size; ++i)
            if (i < KeyStore.TargetOffset || i >= KeyStore.TargetOffset + 32)
                Check(memory.Data[i] == original[i], "Data outside group-8 key changed");
        Check(KeyStore.PatchUnique(memory, new ulong[] { FakeMemory.Address }, Replacement) && memory.Writes == 1,
              "Already configured store was rewritten");
        memory = new FakeMemory(); memory.IgnoreWrite = true;
        bool rejected = false;
        try { KeyStore.PatchUnique(memory, new ulong[] { FakeMemory.Address }, Replacement); }
        catch (IOException) { rejected = true; }
        Check(rejected, "Failed readback was accepted");
        Console.WriteLine("LOCAL KEY SCANNER TESTS OK: " + checks + " checks; native Windows launch not exercised.");
    }
}
