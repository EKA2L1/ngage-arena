#include <e32base.h>

// AirPlay's billing plug-in uses a GCC 2.x vtable and export ordinal 1.
struct ArenaBilling {
    const void* const* vtable;
    TBuf<72> host;
    TBuf8<17> version;
};
static void Initialize(ArenaBilling*) {}
static void Reserved(ArenaBilling*) {}
static void Complete(TRequestStatus& status, TInt result) {
    TRequestStatus* request = &status;
    User::RequestComplete(request, result);
}
static void Authorize(ArenaBilling*, TUint32, TUint16, const TDesC8&, TUint32, TRequestStatus& status) {
    Complete(status, 152);
}
static void Subscribe(ArenaBilling*, TDes8& ticket, TRequestStatus& status) {
    ticket.Copy(_L8("LOCAL"));
    Complete(status, 151);
}
static void Unsubscribe(ArenaBilling*, TRequestStatus& status) { Complete(status, 154); }
static void Cancel(ArenaBilling*) {}
static void Commit(ArenaBilling*, TRequestStatus& status) { Complete(status, 153); }
static TInt BillingType(ArenaBilling*) { return 0; }
static const TDesC8& Version(ArenaBilling* self) { return self->version; }
static const TBuf<72>& Host(ArenaBilling* self) { return self->host; }
static TInt Port(ArenaBilling*) { return 41001; }
static const void* const VTable[] = {
    0, 0, (const void*)Initialize, (const void*)Reserved,
    (const void*)Authorize, (const void*)Reserved, (const void*)Subscribe,
    (const void*)Unsubscribe, (const void*)Cancel, (const void*)Commit,
    (const void*)BillingType, (const void*)Version, (const void*)Host, (const void*)Port
};
extern "C" EXPORT_C ArenaBilling* NewBilling() {
    ArenaBilling* self = new(ELeave) ArenaBilling;
    self->vtable = VTable;
    self->host.Copy(_L("arena.cng.n-gage.com"));
    self->version.Copy(_L8("local-1"));
    return self;
}
GLDEF_C TInt E32Dll(TDllReason) { return KErrNone; }
