using Microsoft.AspNetCore.Diagnostics;
using Microsoft.AspNetCore.Mvc;
using AuthLens.Application;
using AuthLens.Domain.Analysis;
using AuthLens.Domain.Csv;
using AuthLens.Domain.Roles;

namespace AuthLens.Api;

/// <summary>Maps domain exceptions to RFC 9457 problem details. Unexpected errors are logged with the correlation id and return no internals.</summary>
public sealed class ProblemMapper(IProblemDetailsService problems, ILogger<ProblemMapper> logger) : IExceptionHandler
{
    public async ValueTask<bool> TryHandleAsync(HttpContext context, Exception exception, CancellationToken cancellationToken)
    {
        var (status, title) = exception switch
        {
            DomainValidationException or CsvFormatException or ArgumentException or BadHttpRequestException => (400, exception.Message),
            NotFoundException => (404, exception.Message),
            ImportConflictException => (409, exception.Message),
            OperationCanceledException when context.RequestAborted.IsCancellationRequested => (499, "Request cancelled."),
            _ => (500, "An unexpected error occurred."),
        };
        if (status == 500) logger.LogError(exception, "Unhandled request error");
        context.Response.StatusCode = status;
        context.Response.Headers[RequestBoundary.CorrelationHeader] = context.TraceIdentifier; // the exception handler cleared the response headers
        return await problems.TryWriteAsync(new ProblemDetailsContext
        {
            HttpContext = context, Exception = exception,
            ProblemDetails = new ProblemDetails { Status = status, Title = title, Detail = title, Extensions = { ["correlation_id"] = context.TraceIdentifier } }, // detail: what the React client shows
        });
    }
}
