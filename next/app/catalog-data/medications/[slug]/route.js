import { instructionProxy, rejectInstructionProxyMethod } from '../../../../lib/instructionProxy.mjs';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(request, { params }) {
  const { slug } = await params;
  return instructionProxy.medication(request, slug);
}

export const HEAD = rejectInstructionProxyMethod;
export const POST = rejectInstructionProxyMethod;
export const PUT = rejectInstructionProxyMethod;
export const PATCH = rejectInstructionProxyMethod;
export const DELETE = rejectInstructionProxyMethod;
export const OPTIONS = rejectInstructionProxyMethod;
