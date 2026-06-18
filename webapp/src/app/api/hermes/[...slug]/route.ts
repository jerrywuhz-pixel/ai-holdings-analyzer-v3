import { NextRequest } from 'next/server';
import { proxyToBackend } from '@/lib/backend-proxy';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest, { params }: { params: Promise<{ slug?: string[] }> }) {
  const { slug } = await params;
  return proxyToBackend(request, 'hermes', slug ?? []);
}

export async function POST(request: NextRequest, { params }: { params: Promise<{ slug?: string[] }> }) {
  const { slug } = await params;
  return proxyToBackend(request, 'hermes', slug ?? []);
}

export async function PUT(request: NextRequest, { params }: { params: Promise<{ slug?: string[] }> }) {
  const { slug } = await params;
  return proxyToBackend(request, 'hermes', slug ?? []);
}

export async function PATCH(request: NextRequest, { params }: { params: Promise<{ slug?: string[] }> }) {
  const { slug } = await params;
  return proxyToBackend(request, 'hermes', slug ?? []);
}

export async function DELETE(request: NextRequest, { params }: { params: Promise<{ slug?: string[] }> }) {
  const { slug } = await params;
  return proxyToBackend(request, 'hermes', slug ?? []);
}

export async function HEAD(request: NextRequest, { params }: { params: Promise<{ slug?: string[] }> }) {
  const { slug } = await params;
  return proxyToBackend(request, 'hermes', slug ?? []);
}

export async function OPTIONS(request: NextRequest, { params }: { params: Promise<{ slug?: string[] }> }) {
  const { slug } = await params;
  return proxyToBackend(request, 'hermes', slug ?? []);
}
