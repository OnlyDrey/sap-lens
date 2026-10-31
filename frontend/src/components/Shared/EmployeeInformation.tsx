import { sentenceCase } from '@/lib/labels'
import { directoryDisplayName } from '@/lib/directoryDisplayName'
export interface Employee {
  id: string
  name: string
  email: string
  department: string
  title: string
  site: string
  username: string
  account_status: string
  manager: {
    name: string
    email: string
    department: string
    title: string
    username: string
    status: string
    employee_id: string | null
  }
}

const label = sentenceCase

export function EmployeeInformation({
  employee,
  onManager,
}: {
  employee: Employee
  onManager?: (id: string) => void
}) {
  return (
    <dl className="information-list">
      <dt>Name</dt>
      <dd>{directoryDisplayName(employee.name) || 'Unknown'}</dd>
      <dt>Email</dt>
      <dd>{employee.email || 'Missing'}</dd>
      <dt>Department</dt>
      <dd>{employee.department || 'Unknown'}</dd>
      <dt>Job title</dt>
      <dd>{employee.title || 'Unknown'}</dd>
      <dt>Site</dt>
      <dd>{employee.site || 'Unknown'}</dd>
      <dt>AD username</dt>
      <dd>{employee.username || 'Unknown'}</dd>
      <dt>AD account</dt>
      <dd>{employee.account_status}</dd>
      <dt>Manager</dt>
      <dd>
        {directoryDisplayName(employee.manager.name) || 'Not provided'} ·{' '}
        {label(employee.manager.status)}
        {employee.manager.employee_id != null && onManager && (
          <button
            className="settings-secondary-button ml-2"
            onClick={() => onManager(employee.manager.employee_id!)}
          >
            View manager
          </button>
        )}
      </dd>
      <dt>Manager email</dt>
      <dd>{employee.manager.email || 'Not provided'}</dd>
      <dt>Manager department</dt>
      <dd>{employee.manager.department || 'Not provided'}</dd>
      <dt>Manager job title</dt>
      <dd>{employee.manager.title || 'Not provided'}</dd>
      <dt>Manager AD username</dt>
      <dd>{employee.manager.username || 'Not provided'}</dd>
    </dl>
  )
}
